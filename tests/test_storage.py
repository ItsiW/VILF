import hashlib
from pathlib import Path

import pytest

from scripts.storage import CONTENT_TYPES, GCSStorage, LocalStorage, guess_content_type, storage_from_url


@pytest.fixture
def store(tmp_path):
    return LocalStorage(tmp_path / "root")


def test_put_get_exists_delete(store):
    assert not store.exists("a/b/c.txt")
    store.put("a/b/c.txt", b"hello", content_type="text/plain")
    assert store.exists("a/b/c.txt")
    assert store.get("a/b/c.txt") == b"hello"
    store.put("a/b/c.txt", b"again", content_type="text/plain", cache_control="no-cache")
    assert store.get("a/b/c.txt") == b"again"
    store.delete("a/b/c.txt")
    store.delete("a/b/c.txt")
    assert not store.exists("a/b/c.txt")
    with pytest.raises(FileNotFoundError):
        store.get("a/b/c.txt")


def test_copy_and_listing(store):
    store.put("img/food/x.jpg", b"jpeg", content_type="image/jpeg")
    store.put("index.html", b"<p>", content_type="text/html")
    store.copy("img/food/x.jpg", "img/thumb/x.jpg")
    assert store.get("img/thumb/x.jpg") == b"jpeg"
    assert store.listing() == {
        "img/food/x.jpg": hashlib.md5(b"jpeg").hexdigest(),
        "img/thumb/x.jpg": hashlib.md5(b"jpeg").hexdigest(),
        "index.html": hashlib.md5(b"<p>").hexdigest(),
    }
    assert set(store.listing("img/thumb")) == {"img/thumb/x.jpg"}
    assert LocalStorage(Path("/nonexistent/dir")).listing() == {}


def test_atomic_write_leaves_no_tmp(store):
    store.put("deep/file.bin", b"\x00" * 100, content_type="application/octet-stream")
    leftovers = [p for p in store.root.rglob("*") if p.name.startswith(".tmp-")]
    assert leftovers == []


def test_public_url_and_unsafe_keys(store):
    assert store.public_url("a/b.txt") == f"file://{(store.root / 'a' / 'b.txt').resolve()}"
    for bad in ["/etc/passwd", "../x", "a/../../x", ""]:
        with pytest.raises(ValueError):
            store.put(bad, b"", content_type="text/plain")


@pytest.mark.parametrize("suffix,expected", list(CONTENT_TYPES.items()))
def test_guess_content_type_table(suffix, expected):
    assert guess_content_type(f"dir/file{suffix}") == expected


def test_guess_content_type_fallbacks():
    assert guess_content_type("X.JPG") == "image/jpeg"
    assert guess_content_type("logo.svg") == "image/svg+xml"
    assert guess_content_type("weird.zzzunknown") == "application/octet-stream"
    assert guess_content_type("noext") == "application/octet-stream"


def test_storage_from_url(tmp_path):
    s = storage_from_url(str(tmp_path))
    assert isinstance(s, LocalStorage) and s.root == tmp_path
    with pytest.raises(ValueError):
        storage_from_url("gs://bucket/prefix")
    with pytest.raises(ValueError):
        storage_from_url("gs://")


def test_gcs_public_url_without_client():
    s = GCSStorage.__new__(GCSStorage)
    s.name = "vilf-org"
    assert s.public_url("img/x.jpg") == "https://storage.googleapis.com/vilf-org/img/x.jpg"
