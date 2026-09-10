"""Blob storage behind one small protocol: a local directory or a GCS bucket."""

import base64
import hashlib
import mimetypes
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".xml": "application/xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".css": "text/css",
    ".js": "text/javascript",
}


def guess_content_type(key: str) -> str:
    suffix = PurePosixPath(key).suffix.lower()
    if suffix in CONTENT_TYPES:
        return CONTENT_TYPES[suffix]
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


class Storage(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str, cache_control: str | None = None) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def copy(self, src: str, dst: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def listing(self, prefix: str = "") -> dict[str, str]: ...
    def public_url(self, key: str) -> str: ...


class LocalStorage:
    """Files under `root`; writes are atomic (tmp file + rename)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        parts = PurePosixPath(key).parts
        if not parts or key.startswith("/") or ".." in parts:
            raise ValueError(f"unsafe storage key {key!r}")
        return self.root.joinpath(*parts)

    def put(self, key: str, data: bytes, *, content_type: str, cache_control: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp.name, path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def copy(self, src: str, dst: str) -> None:
        self.put(dst, self.get(src), content_type=guess_content_type(dst))

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def listing(self, prefix: str = "") -> dict[str, str]:
        if not self.root.is_dir():
            return {}
        result = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name.startswith(".tmp-"):
                continue
            key = path.relative_to(self.root).as_posix()
            if key.startswith(prefix):
                result[key] = hashlib.md5(path.read_bytes()).hexdigest()
        return result

    def public_url(self, key: str) -> str:
        return f"file://{self._path(key).resolve()}"


class GCSStorage:
    """A GCS bucket; google.cloud.storage is imported lazily so tests never need it."""

    def __init__(self, bucket: str):
        from google.cloud import storage

        self.name = bucket
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket)

    def put(self, key: str, data: bytes, *, content_type: str, cache_control: str | None = None) -> None:
        blob = self.bucket.blob(key)
        if cache_control:
            blob.cache_control = cache_control
        blob.upload_from_string(data, content_type=content_type)

    def get(self, key: str) -> bytes:
        from google.api_core.exceptions import NotFound

        try:
            return self.bucket.blob(key).download_as_bytes()
        except NotFound as e:
            raise FileNotFoundError(key) from e

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self.bucket.blob(key).delete()
        except NotFound:
            pass

    def copy(self, src: str, dst: str) -> None:
        self.bucket.copy_blob(self.bucket.blob(src), self.bucket, dst)

    def exists(self, key: str) -> bool:
        return self.bucket.blob(key).exists()

    def listing(self, prefix: str = "") -> dict[str, str]:
        return {
            blob.name: base64.b64decode(blob.md5_hash).hex()
            for blob in self.client.list_blobs(self.bucket, prefix=prefix)
            if blob.md5_hash
        }

    def public_url(self, key: str) -> str:
        return f"https://storage.googleapis.com/{self.name}/{key}"


def storage_from_url(url: str) -> Storage:
    """'gs://<bucket>' -> GCSStorage, anything else is a local directory."""
    url = str(url)
    if url.startswith("gs://"):
        bucket = url[len("gs://"):].rstrip("/")
        if not bucket or "/" in bucket:
            raise ValueError(f"expected gs://<bucket>, got {url!r}")
        return GCSStorage(bucket)
    return LocalStorage(Path(url))
