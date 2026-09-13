"""Incremental original-photo copy to the Mac; never mirrors source deletions."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile

from .storage import LocalStorage


def checksum(path):
    with path.open("rb") as source:
        return base64.b64encode(hashlib.file_digest(source, "md5").digest()).decode()


def copy_photos(bucket, destination):
    destination = Path(destination)
    blobs = list(bucket.list_blobs(prefix="originals/"))
    if not blobs:
        raise ValueError("No originals found; refusing to report an empty photo backup")
    copied = 0
    total_bytes = 0
    for blob in blobs:
        key = PurePosixPath(blob.name)
        if len(key.parts) != 2 or key.parts[0] != "originals" or key.parts[1] in {".", ".."}:
            raise ValueError("Unexpected original-photo path")
        if not blob.md5_hash:
            raise ValueError("Original photo is missing a checksum")
        path = destination / key.name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.is_file() or checksum(path) != blob.md5_hash:
            with tempfile.NamedTemporaryFile(dir=destination, prefix=".download-", delete=False) as temp:
                temporary = Path(temp.name)
            try:
                blob.download_to_filename(str(temporary), if_generation_match=blob.generation, timeout=60)
                if checksum(temporary) != blob.md5_hash:
                    raise ValueError("Downloaded photo checksum mismatch")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            copied += 1
        total_bytes += path.stat().st_size
    return {"originals": len(blobs), "bytes": total_bytes, "downloaded": copied}


def main():
    from google.cloud import storage

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--started", required=True)
    parser.add_argument("--destination", type=Path, default=Path.home() / "Backups/vilf/photos")
    args = parser.parse_args()
    result = copy_photos(storage.Client().bucket("vilf-media"), args.destination)
    result["started_at"] = args.started
    LocalStorage(Path(__file__).resolve().parents[1] / ".backups").put(
        "status/mac-photos.json", json.dumps(result).encode(), content_type="application/json")
    print(f"Photos: {result['originals']} originals verified, {result['downloaded']} downloaded", flush=True)


if __name__ == "__main__":
    main()
