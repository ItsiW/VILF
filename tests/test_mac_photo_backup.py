import base64
import hashlib
from types import SimpleNamespace

import pytest

from scripts.mac_photo_backup import copy_photos


def blob(name, data, downloads, *, corrupt=False):
    def download(path, **kwargs):
        from pathlib import Path
        assert kwargs["if_generation_match"] == 1
        downloads.append(name)
        Path(path).write_bytes(b"corrupt" if corrupt else data)
    return SimpleNamespace(name=name, md5_hash=base64.b64encode(hashlib.md5(data).digest()).decode(),
                           generation=1, download_to_filename=download)


def test_incremental_copy_preserves_deleted_source_files(tmp_path):
    downloads = []
    objects = [blob("originals/a.jpg", b"first", downloads)]
    bucket = SimpleNamespace(list_blobs=lambda **_: objects)
    assert copy_photos(bucket, tmp_path)["downloaded"] == 1
    assert copy_photos(bucket, tmp_path)["downloaded"] == 0
    objects[:] = [blob("originals/b.jpg", b"second", downloads)]
    assert copy_photos(bucket, tmp_path)["downloaded"] == 1
    assert (tmp_path / "a.jpg").read_bytes() == b"first"
    objects[:] = [blob("originals/b.jpg", b"replacement", downloads)]
    assert copy_photos(bucket, tmp_path)["downloaded"] == 1
    assert (tmp_path / "b.jpg").read_bytes() == b"replacement"


def test_failed_download_preserves_previous_photo(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"original")
    bucket = SimpleNamespace(list_blobs=lambda **_: [blob("originals/a.jpg", b"new", [], corrupt=True)])
    with pytest.raises(ValueError, match="checksum"):
        copy_photos(bucket, tmp_path)
    assert (tmp_path / "a.jpg").read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [tmp_path / "a.jpg"]


@pytest.mark.parametrize("name", ["originals/../outside.jpg", "originals/", "/originals/a.jpg"])
def test_unsafe_paths_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="path"):
        copy_photos(SimpleNamespace(list_blobs=lambda **_: [blob(name, b"data", [])]), tmp_path)


def test_empty_source_is_not_success(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        copy_photos(SimpleNamespace(list_blobs=lambda **_: []), tmp_path)
