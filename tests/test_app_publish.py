"""The /publish and /publishes screens: real publishes into LocalStorage under tmp_path."""

import html
import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.routes.publish as publish_routes
from app.main import create_app
from scripts import repo, runs
from scripts.config import REPO_ROOT, Settings
from scripts.publish import GcpCdnInvalidator, PublishResult

FIXTURES = Path(__file__).parent / "fixtures"
ROWS = json.loads((FIXTURES / "snapshot.json").read_text())
SLUGS = sorted(r["slug"] for r in ROWS)

IAP = {"X-Goog-IAP-JWT-Assertion": "jwt", "X-Goog-Authenticated-User-Email": "accounts.google.com:me@example.com"}


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    # only the top-level static files: the gitignored static/img cache is 70+ MB locally
    static = tmp_path / "static"
    static.mkdir()
    for file in (REPO_ROOT / "static").iterdir():
        if file.is_file():
            shutil.copy(file, static / file.name)
    monkeypatch.setattr(publish_routes, "STATIC_DIR", static)

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
        client.site_dir = tmp_path / "site"
        client.media_dir = tmp_path / "media"
        return client

    return make


@pytest.fixture
def client(make_client):
    return make_client()


def text(response):
    return html.unescape(response.text)


def row(client, slug):
    with client.engine.begin() as conn:
        return repo.get(conn, slug)


def all_rows(client):
    with client.engine.begin() as conn:
        return repo.all_rows(conn)


def update(client, slug, fields):
    with client.engine.begin() as conn:
        return repo.update(conn, slug, fields)


def recent(client):
    with client.engine.begin() as conn:
        return runs.recent(conn)


def publish_button(page):
    match = re.search(r"<button[^>]*>Publish</button>", page)
    assert match, page
    return match.group(0)


def test_publish_page_before_first_publish(client):
    r = client.get("/publish")
    assert r.status_code == 200
    page = text(r)
    assert "Added (6)" in page
    for fixture in ROWS:
        assert fixture["name"] in page and f'href="/places/{fixture["slug"]}"' in page
    assert "Cannot publish" not in page and "None yet" in page
    assert "disabled" not in publish_button(page)
    assert 'hx-confirm="Publish the site now?"' in page and 'name="force"' in page
    assert 'href="/publishes"' in page
    partial = client.get("/publish", headers={"HX-Request": "true"}).text
    assert 'id="pending"' in partial and "<nav>" not in partial


def test_publish_runs_and_reloads(client):
    r = client.post("/publish", data={})
    assert r.status_code == 200
    body = text(r)
    assert "Publish ok" in body
    uploaded = int(re.search(r"Publish ok: (\d+) uploaded", body).group(1))
    assert uploaded > 0
    assert "snapshot: snapshots/" in body and "skipped (not configured)" in body
    assert "changes: +6 -0 ~0" in body
    assert 'hx-get="/publish" hx-trigger="load"' in body
    assert (client.site_dir / "places" / "test-place" / "index.html").exists()
    assert (client.site_dir / "sitemap.xml").exists()
    assert len(list((client.media_dir / "snapshots").iterdir())) == 1
    assert not any(repo.is_dirty(r) for r in all_rows(client))
    run = recent(client)[0]
    assert run["kind"] == "publish" and run["status"] == "ok" and run["by_email"] == "dev@localhost"
    assert run["summary"] == f"{uploaded} uploaded, 0 deleted, 0 unchanged"
    page = text(client.get("/publish"))
    assert "Nothing to publish" in page and "Added (" not in page
    assert "Last publish" in page and run["summary"] in page and run["snapshot_key"] in page
    assert "dev@localhost" in page and "None yet" not in page
    # a second publish uploads nothing
    body = text(client.post("/publish", data={}))
    assert "Publish ok: 0 uploaded, 0 deleted" in body and "changes: +0 -0 ~0" in body


def test_changed_diff_after_edit(client):
    client.post("/publish", data={})
    old_body = row(client, "test-place")["body"]
    new_body = "Get the **pad thai** and the **spring rolls**, both are the best things here."
    update(client, "test-place", {"taste": 3, "body": new_body})
    page = text(client.get("/publish"))
    assert "Changed (1)" in page and "taste: 2 -> 3" in page
    assert f"review text changed ({len(old_body.split())} words -> {len(new_body.split())} words)" in page
    pending = page[page.index('id="pending"'):]
    assert "updated_at" not in pending and "published_at" not in pending and "Added (" not in pending
    assert "disabled" not in publish_button(page)


def test_removed_diff(client):
    client.post("/publish", data={})
    update(client, "draft-place", {"published_at": None})  # deletable again
    with client.engine.begin() as conn:
        repo.delete(conn, "draft-place")
    page = text(client.get("/publish"))
    assert "Removed (1)" in page and "draft-place" in page


def test_running_row_gives_409(client):
    with client.engine.begin() as conn:
        runs.start(conn, "publish")
    r = client.post("/publish", data={})
    assert r.status_code == 409 and "already running" in r.text
    assert not (client.site_dir / "places").exists()
    page = text(client.get("/publish"))
    assert "is still running" in page and "disabled" in publish_button(page)


def test_invalid_row_blocks_publish(client):
    update(client, "test-place", {"body": "No dish here."})
    page = text(client.get("/publish"))
    assert "Cannot publish until these are fixed" in page
    assert "test-place</a>: taste: highlight a dish in bold" in page
    assert 'href="/places/test-place"' in page and "disabled" in publish_button(page)
    r = client.post("/publish", data={})
    assert r.status_code == 200
    assert "Publish failed" in r.text and "highlight a dish in bold" in text(r)
    assert recent(client)[0]["summary"] == "1 validation problem(s)"
    assert not (client.site_dir / "places").exists()


def test_force_flag_and_cdn_passthrough(make_client, monkeypatch):
    calls = []

    def recorder(conn, **kw):
        calls.append(kw)
        return PublishResult(1, "ok", 0, 0, 0, None, None, None, False, 0.1)

    monkeypatch.setattr(publish_routes.publish_mod, "publish", recorder)
    client = make_client()
    r = client.post("/publish", data={"force": "1"})
    assert r.status_code == 200 and "Publish ok: 0 uploaded" in r.text
    assert calls[-1]["force"] is True and calls[-1]["by_email"] == "dev@localhost" and calls[-1]["cdn"] is None
    assert calls[-1]["static_dir"] == publish_routes.STATIC_DIR
    client.post("/publish", data={})
    assert calls[-1]["force"] is False

    client = make_client(google_cloud_project="p", url_map="m")
    r = client.post("/publish", data={})
    cdn = calls[-1]["cdn"]
    assert isinstance(cdn, GcpCdnInvalidator) and (cdn.project, cdn.url_map) == ("p", "m")
    assert "CDN: failed" in r.text  # configured but the fake result reports no invalidation


def test_history_lists_runs(client):
    assert "No publishes yet" in client.get("/publishes").text
    client.post("/publish", data={})
    with client.engine.begin() as conn:
        runs.append(conn, "restore", "6 places restored from x", snapshot_key="snapshots/x.json")
        runs.append(conn, "check", "ignored")
    r = client.get("/publishes")
    assert r.status_code == 200
    page = r.text
    assert "6 places restored from x" in page and "snapshots/x.json" in page
    assert "ignored" not in page
    publish_key = recent(client)[-1]["snapshot_key"]
    assert publish_key in page
    assert page.index("snapshots/x.json") < page.index(publish_key)  # newest first
    assert 'href="/publish"' in page


def test_auth(make_client):
    client = make_client(admin_email="me@example.com")
    for path in ("/publish", "/publishes"):
        assert client.get(path).status_code == 403
        assert client.get(path, headers=IAP).status_code == 200
    assert client.post("/publish", data={}).status_code == 403
