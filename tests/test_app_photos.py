import json
import sys
import types
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from scripts import repo
from scripts.config import Settings

ROWS = json.loads((Path(__file__).parent / "fixtures" / "snapshot.json").read_text())


@pytest.fixture
def make_client(tmp_path):
    def make(**overrides):
        settings = Settings(
            database_url=f"sqlite:///{tmp_path}/t.db",
            media_storage=str(tmp_path / "media"),
            site_storage=str(tmp_path / "site"),
            **overrides,
        )
        application = create_app(settings)
        with application.state.engine.begin() as conn:
            repo.from_snapshot_rows(conn, ROWS, replace=True)
        client = TestClient(application, follow_redirects=False)
        client.engine = application.state.engine
        client.media_dir = tmp_path / "media"
        return client

    return make


@pytest.fixture
def client(make_client):
    return make_client()


def row(client, slug):
    with client.engine.begin() as conn:
        return repo.get(conn, slug)


def png_bytes(w, h):
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // max(w - 1, 1), y * 255 // max(h - 1, 1), 90)
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def upload(client, slug, data, name="x.png", content_type="image/png"):
    return client.post(f"/places/{slug}/photo", files={"photo": (name, data, content_type)})


FILES = ["originals/draft-place.jpg", "img/food/draft-place.jpg", "img/food/draft-place.webp",
         "img/thumb/draft-place.jpg", "img/thumb/draft-place.webp"]


def test_panel_without_photo_has_upload_only(client):
    html = client.get("/places/draft-place/photo").text
    assert 'hx-post="/places/draft-place/photo"' in html and 'accept="image/*,.heic"' in html
    assert "photo/preview" not in html and "photo/crop" not in html and "Delete photo" not in html
    assert client.get("/places/nope/photo").status_code == 404
    assert 'hx-trigger="change[' in html
    assert 'hx-disabled-elt="#photo-panel input, #photo-panel button"' in html
    assert 'role="status"' in html
    assert '>Upload</button>' not in html
    assert 'this.reset()' in html  # the same file can be chosen again after a failed request


def test_preview_source_is_uncropped_and_bounded(client):
    assert client.get('/places/draft-place/photo/preview-source').status_code == 404
    upload(client, 'draft-place', png_bytes(800, 1600))
    response = client.get('/places/draft-place/photo/preview-source')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert Image.open(BytesIO(response.content)).size == (600, 1200)


def test_upload_tall_photo(client):
    r = upload(client, "draft-place", png_bytes(800, 1000))
    assert r.status_code == 200
    assert "/places/draft-place/photo/preview-source?v=" in r.text
    assert "style.objectPosition" in r.text
    assert "oninput=\"document.getElementById('crop-preview').src" not in r.text
    assert "/media/img/thumb/draft-place.jpg?v=" in r.text
    assert 'type="range" name="crop_y"' in r.text and "Delete photo" in r.text
    for key in FILES:
        assert (client.media_dir / key).is_file(), key
    after = row(client, "draft-place")
    assert after["photo_key"] == "originals/draft-place.jpg"
    assert (after["photo_width"], after["photo_height"], after["photo_crop_y"]) == (800, 1000, 0.5)
    assert Image.open(client.media_dir / "img/food/draft-place.jpg").size == (1200, 675)


def test_upload_wide_photo_hides_slider(client):
    r = upload(client, "draft-place", png_bytes(1600, 900))
    assert r.status_code == 200
    assert 'type="range"' not in r.text and "nothing to crop" in r.text
    assert "/places/draft-place/photo/preview-source?v=" in r.text


def test_media_route(client):
    upload(client, "draft-place", png_bytes(800, 1000))
    r = client.get("/media/img/thumb/draft-place.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert Image.open(BytesIO(r.content)).size == (426, 240)
    assert client.get("/media/nope.jpg").status_code == 404
    assert client.get("/media/../etc/passwd").status_code == 404


def test_preview_endpoint(client):
    assert client.get("/places/draft-place/photo/preview?crop_y=0.2").status_code == 404
    upload(client, "draft-place", png_bytes(800, 1000))
    r = client.get("/places/draft-place/photo/preview?crop_y=0.2")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "no-store"
    im = Image.open(BytesIO(r.content))
    assert im.format == "JPEG" and im.size[0] == 600


def test_crop_updates_variants_and_column(client):
    upload(client, "draft-place", png_bytes(800, 1000))
    before = (client.media_dir / "img/food/draft-place.jpg").read_bytes()
    r = client.post("/places/draft-place/photo/crop", data={"crop_y": "0.1"})
    assert r.status_code == 200 and "object-position: 50% 10.0%" in r.text
    assert row(client, "draft-place")["photo_crop_y"] == 0.1
    assert (client.media_dir / "img/food/draft-place.jpg").read_bytes() != before
    r = client.post("/places/draft-place/photo/crop", data={"crop_y": "7"})
    assert row(client, "draft-place")["photo_crop_y"] == 1.0
    r = client.post("/places/bare-place/photo/crop", data={"crop_y": "0.1"})
    assert r.status_code == 200 and "No photo to crop" in r.text


def test_delete_photo(client):
    upload(client, "draft-place", png_bytes(800, 1000))
    r = client.post("/places/draft-place/photo/delete")
    assert r.status_code == 200
    assert "photo/preview" not in r.text and 'hx-post="/places/draft-place/photo"' in r.text
    for key in FILES:
        assert not (client.media_dir / key).exists(), key
    after = row(client, "draft-place")
    assert after["photo_key"] is None and after["photo_width"] is None and after["photo_height"] is None
    assert client.post("/places/draft-place/photo/delete").status_code == 200


def test_garbage_upload_shows_error(client):
    r = upload(client, "draft-place", b"not an image at all", name="x.jpg", content_type="image/jpeg")
    assert r.status_code == 200 and "cannot decode image" in r.text
    assert row(client, "draft-place")["photo_key"] is None
    assert not (client.media_dir / "originals").exists()
    r = upload(client, "draft-place", b"", name="x.jpg", content_type="image/jpeg")
    assert r.status_code == 200 and "Choose a photo" in r.text


def test_cdn_invalidation_after_crop_and_delete(make_client, monkeypatch):
    calls = []

    class Fake:
        def __init__(self, project, url_map):
            calls.append(("init", project, url_map))

        def invalidate(self, paths):
            calls.append(("invalidate", list(paths)))

    monkeypatch.setitem(sys.modules, "scripts.publish", types.SimpleNamespace(GcpCdnInvalidator=Fake))
    client = make_client(google_cloud_project="p", url_map="m")
    paths = ["/img/food/draft-place.jpg", "/img/food/draft-place.webp",
             "/img/thumb/draft-place.jpg", "/img/thumb/draft-place.webp"]
    upload(client, "draft-place", png_bytes(800, 1000))
    assert calls == []  # first upload: new files, nothing cached yet
    upload(client, "draft-place", png_bytes(900, 1100))
    assert calls == [("init", "p", "m"), ("invalidate", paths)]  # replacing rewrites cached keys
    client.post("/places/draft-place/photo/crop", data={"crop_y": "0.3"})
    assert calls[-1] == ("invalidate", paths)
    client.post("/places/draft-place/photo/delete")
    assert calls[-1] == ("invalidate", paths)


def test_cdn_invalidation_skipped_without_config_or_module(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "scripts.publish", None)  # import raises ImportError
    upload(client, "draft-place", png_bytes(800, 1000))
    assert client.post("/places/draft-place/photo/crop", data={"crop_y": "0.3"}).status_code == 200


def test_deleting_place_removes_photo_files(client):
    upload(client, "draft-place", png_bytes(800, 1000))
    for key in FILES:
        assert (client.media_dir / key).is_file(), key
    r = client.post("/places/draft-place/delete")
    assert r.status_code == 303
    assert row(client, "draft-place") is None
    for key in FILES:
        assert not (client.media_dir / key).exists(), key
