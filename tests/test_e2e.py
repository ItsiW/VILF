"""End to end, offline: admin app -> publish -> site storage.

One test strings the system together the way a review reaches vilf.org:
look a restaurant up through the admin's Google lookup (search_text/get_place
monkeypatched to the LION fixture), create the row, upload a photo, save a
crop, then call scripts.publish.publish() against the same media and site
storages the app uses and check what landed in the site, the media and the
runs table. A second publish must be a no-op.

The /sync and /publish routes are deliberately not used (they belong to another
package and may be absent); publish() is called directly. No network: the
autouse guard in conftest.py fails any HTTP call.
"""

import json
import shutil
from datetime import date
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

import app.routes.places as places_routes
from app.main import create_app
from scripts import photos, repo, runs
from scripts.config import Settings
from scripts.places import parse_place
from scripts.publish import publish

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
ROWS = json.loads((FIXTURES / "snapshot.json").read_text(encoding="utf-8"))
LION = parse_place(json.loads((FIXTURES / "places" / "details_full.json").read_text(encoding="utf-8")))
SEARCH = [
    parse_place(p)
    for p in json.loads((FIXTURES / "places" / "search_text.json").read_text(encoding="utf-8"))["places"]
]
TODAY = date(2026, 9, 10)
SLUG = "lion-dance-cafe"

FORM = {
    "name": "Lion Dance Cafe",
    "cuisine": "Singaporean",
    "address": "380 17th St",
    "area": "Downtown Oakland",
    "city": "Oakland",
    "lat": "37.8061",
    "lon": "-122.2683",
    "phone": "+15105550199",
    "menu": "https://example.com/lion-menu",
    "website": "https://example.com/lion-dance",
    "place_id": "ChIJfixtureLionDance",
    "visited": "2026-09-01",
    "taste": "3",
    "value": "2",
    "drinks": "1",
    "body": "Great **laksa** and the best coffee in town.",
}


def make_site_root(root: Path) -> Path:
    """html/ and about.md from the repo, top-level static files only (not the static/img cache)."""
    (root / "html").symlink_to(REPO_ROOT / "html")
    (root / "about.md").symlink_to(REPO_ROOT / "about.md")
    (root / "static").mkdir()
    for file in (REPO_ROOT / "static").iterdir():
        if file.is_file():
            shutil.copy(file, root / "static" / file.name)
    return root


def jpeg_bytes(w: int, h: int) -> bytes:
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // max(w - 1, 1), y * 255 // max(h - 1, 1), 90)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_create_photo_crop_publish(tmp_path, monkeypatch):
    (tmp_path / "root").mkdir()
    root = make_site_root(tmp_path / "root")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/e2e.db",
        media_storage=str(tmp_path / "media"),
        site_storage=str(tmp_path / "site"),
    )
    application = create_app(settings)
    engine, media, site = application.state.engine, application.state.media, application.state.site
    with engine.begin() as conn:
        repo.from_snapshot_rows(conn, ROWS, replace=True)
    monkeypatch.setattr(places_routes, "search_text", lambda q, **k: SEARCH)
    monkeypatch.setattr(places_routes, "get_place", lambda pid, **k: LION)
    client = TestClient(application, follow_redirects=False)

    # 1. lookup -> pick -> create
    r = client.post("/places/new/search", data={"q": "lion"})
    assert r.status_code == 200
    assert "Lion Dance Cafe" in r.text and 'hx-post="/places/new/pick"' in r.text
    r = client.post("/places/new/pick", data={"place_id": LION.place_id})
    assert r.status_code == 200 and 'value="380 17th St"' in r.text
    r = client.post("/places", data=FORM)
    assert r.status_code == 303 and r.headers["location"] == f"/places/{SLUG}?flash=created"
    with engine.begin() as conn:
        row = repo.get(conn, SLUG)
    assert row is not None and row["photo_key"] is None and repo.is_dirty(row)

    # 2. photo upload (tall, so the crop slider applies) and a crop
    r = client.post(f"/places/{SLUG}/photo", files={"photo": ("food.jpg", jpeg_bytes(800, 1000), "image/jpeg")})
    assert r.status_code == 200 and 'type="range" name="crop_y"' in r.text
    before = media.get(f"img/food/{SLUG}.jpg")
    r = client.post(f"/places/{SLUG}/photo/crop", data={"crop_y": "0.2"})
    assert r.status_code == 200
    with engine.begin() as conn:
        row = repo.get(conn, SLUG)
    assert row["photo_key"] == f"originals/{SLUG}.jpg" and row["photo_crop_y"] == 0.2
    assert media.get(f"img/food/{SLUG}.jpg") != before

    # 3. publish with the same storages
    with engine.begin() as conn:
        first = publish(
            conn, media=media, site=site, settings=settings, today=TODAY,
            html_dir=root / "html", static_dir=root / "static", about_path=root / "about.md",
        )
    assert first.status == "ok" and first.error is None
    assert first.uploaded > 0 and first.deleted == 0

    # the page and its feeds
    assert site.exists(f"places/{SLUG}/index.html")
    page = site.get(f"places/{SLUG}/index.html").decode("utf-8")
    assert "Verdict:" not in page
    assert f"/img/food/{SLUG}.webp" in page
    entry = next(p for p in json.loads(site.get("places.json").decode("utf-8")) if p["slug"] == SLUG)
    assert entry["image"] == f"https://vilf.org/img/food/{SLUG}.jpg"
    assert SLUG in site.get("sitemap.xml").decode("utf-8")
    assert not site.listing(prefix="img/")  # the img/ prefix in the site is never written by publish

    # media: original, four variants, exactly one snapshot holding the new row
    keys = media.listing()
    assert f"originals/{SLUG}.jpg" in keys
    for key in photos.variant_keys(SLUG):
        assert key in keys, key
    snapshots = [k for k in keys if k.startswith("snapshots/")]
    assert snapshots == [first.snapshot_key]
    saved = json.loads(media.get(first.snapshot_key).decode("utf-8"))
    assert SLUG in {r["slug"] for r in saved}

    # bookkeeping
    with engine.begin() as conn:
        run = runs.recent(conn)[0]
        assert run["kind"] == "publish" and run["status"] == "ok"
        assert run["snapshot_key"] == first.snapshot_key and run["id"] == first.run_id
        assert not repo.is_dirty(repo.get(conn, SLUG))
        assert SLUG in first.changes.added

    # 4. nothing changed: the second publish uploads and deletes nothing
    with engine.begin() as conn:
        second = publish(
            conn, media=media, site=site, settings=settings, today=TODAY,
            html_dir=root / "html", static_dir=root / "static", about_path=root / "about.md",
        )
    assert second.status == "ok"
    assert (second.uploaded, second.deleted) == (0, 0)
    assert second.unchanged == first.uploaded
    assert not second.changes
