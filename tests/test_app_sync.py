"""The per-place sync panel and the /sync audit page, with Google faked at app.routes.sync."""

import copy
import html
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.routes.sync as sync_routes
from app.main import create_app
from scripts import repo, runs
from scripts.config import Settings
from scripts.places import CONTACT_FIELDS, CORE_FIELDS, PlacesError, parse_place

FIXTURES = Path(__file__).parent / "fixtures"
ROWS = json.loads((FIXTURES / "snapshot.json").read_text())
FULL = json.loads((FIXTURES / "places" / "details_full.json").read_text())
LION = parse_place(FULL)
CLOSED = parse_place(json.loads((FIXTURES / "places" / "details_closed.json").read_text()))

IAP = {"X-Goog-IAP-JWT-Assertion": "jwt", "X-Goog-Authenticated-User-Email": "accounts.google.com:me@example.com"}


def place_with_status(status):
    raw = copy.deepcopy(FULL)
    raw["businessStatus"] = status
    return parse_place(raw)


@pytest.fixture
def make_client(tmp_path, monkeypatch):
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
        monkeypatch.setattr(sync_routes, "get_place", lambda pid, **k: LION)
        monkeypatch.setattr(sync_routes, "search_text", lambda q, **k: [LION])
        client = TestClient(application, follow_redirects=False)
        client.engine = application.state.engine
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


def update(client, slug, fields):
    with client.engine.begin() as conn:
        return repo.update(conn, slug, fields)


def recent(client):
    with client.engine.begin() as conn:
        return runs.recent(conn)


# --- per-place panel ---


def test_edit_page_loads_sync_panel(client):
    page = client.get("/places/test-place").text
    assert 'hx-get="/places/test-place/sync"' in page and 'hx-get="/places/test-place/photo"' in page
    r = client.get("/places/test-place/sync")
    assert r.status_code == 200
    assert "Check against Google" in r.text and 'name="contact"' in r.text
    assert "Never checked" in r.text and "Apply fixes" not in r.text
    assert client.get("/places/nope/sync").status_code == 404


def test_check_shows_mismatches_and_apply(client):
    r = client.post("/places/test-place/sync", data={"contact": "0"})
    assert r.status_code == 200
    body = text(r)
    assert "Current address: 1 Main St | Determined address: 380 17th St" in body
    assert "Current name: Test Place | Determined name: Lion Dance Cafe" in body
    assert "Current latitude: 37.7601 | Determined latitude: 37.8061" in body
    assert "Current longitude: -122.4201 | Determined longitude: -122.2683" in body
    assert 'hx-post="/places/test-place/sync/apply"' in body
    assert 'name="contact" value="0"' in body
    assert row(client, "test-place")["address"] == "1 Main St"
    assert recent(client) == []


def test_check_contact_flag(client, monkeypatch):
    seen = []
    monkeypatch.setattr(sync_routes, "get_place", lambda pid, **k: seen.append(k.get("fields")) or LION)
    r = client.post("/places/test-place/sync", data={"contact": "1"})
    body = text(r)
    assert "Current phone number: +14155551234 | Determined phone number: +15105550199" in body
    assert 'name="contact" value="1"' in body and 'name="contact" value="1" checked' in body
    client.post("/places/test-place/sync", data={"contact": "0"})
    client.post("/places/test-place/sync", data={})
    assert seen == [CONTACT_FIELDS, CORE_FIELDS, CORE_FIELDS]


def test_check_without_place_id_uses_search_and_hides_apply(client, monkeypatch):
    monkeypatch.setattr(sync_routes, "get_place", lambda pid, **k: pytest.fail("get_place called"))
    r = client.post("/places/bare-place/sync", data={"contact": "0"})
    body = text(r)
    assert "(no place_id: matched by search to Lion Dance Cafe, ChIJfixtureLionDance)" in body
    assert "Current address: 3 Main St | Determined address: 380 17th St" in body
    assert "Apply fixes" not in body and "relink" in body.lower()


def test_apply_fixes_updates_row_and_logs(client):
    r = client.post("/places/test-place/sync/apply", data={"contact": "0"})
    assert r.status_code == 200
    body = text(r)
    assert "fixed: address, coordinates" in body
    assert "name kept: Test Place | Google: Lion Dance Cafe" in body
    assert "Current address" not in body
    after = row(client, "test-place")
    assert after["address"] == "380 17th St" and after["lat"] == 37.8061 and after["lon"] == -122.2683
    assert after["city"] == "San Francisco" and after["name"] == "Test Place" and repo.is_dirty(after)
    run = recent(client)[0]
    assert run["kind"] == "check" and run["scope"] == "test-place" and run["by_email"] == "dev@localhost"
    assert run["summary"] == "fixed: address, coordinates" and run["status"] == "ok"
    panel = text(client.get("/places/test-place/sync"))
    assert "Last check:" in panel and "fixed: address, coordinates" in panel


def test_apply_nothing_to_fix(client):
    update(client, "test-place", {"address": "380 17th St", "lat": 37.8061, "lon": -122.2683})
    r = client.post("/places/test-place/sync/apply", data={"contact": "0"})
    assert r.status_code == 200 and "nothing to fix" in r.text
    assert recent(client)[0]["summary"] == "nothing to fix"


def test_apply_refuses_coordinate_clash(client):
    update(client, "draft-place", {"lat": 37.8061, "lon": -122.2683})
    r = client.post("/places/test-place/sync/apply", data={"contact": "0"})
    assert r.status_code == 200 and "not fixed: coordinates" in text(r)
    after = row(client, "test-place")
    assert after["address"] == "1 Main St" and after["lat"] == 37.7601
    assert recent(client) == []


def test_places_error_renders_error(client, monkeypatch):
    def boom(pid, **k):
        raise PlacesError("Places API 403: key missing")

    monkeypatch.setattr(sync_routes, "get_place", boom)
    for path in ("/places/test-place/sync", "/places/test-place/sync/apply"):
        r = client.post(path, data={"contact": "0"})
        assert r.status_code == 200
        assert "Places API 403: key missing" in r.text and 'hx-post="/places/test-place/sync"' in r.text
    assert recent(client) == []


# --- audit page ---


def fake_statuses(monkeypatch, fail_ids=()):
    by_id = {
        "ChIJtestplace0001": LION,
        "ChIJbrackets0002": CLOSED,
        "ChIJdraftplace005": place_with_status("CLOSED_TEMPORARILY"),
    }
    seen = []

    def get(pid, **k):
        seen.append(pid)
        if pid in fail_ids:
            raise PlacesError("quota")
        return by_id[pid]

    monkeypatch.setattr(sync_routes, "get_place", get)
    return seen


def test_sync_page_before_and_after_audit(client, monkeypatch):
    page = client.get("/sync")
    assert page.status_code == 200
    assert "No previous audit" in page.text and 'hx-post="/sync/audit"' in page.text
    assert 'name="mark_closed"' in page.text and "hx-disabled-elt" in page.text and "No runs yet" in page.text

    seen = fake_statuses(monkeypatch)
    r = client.post("/sync/audit", data={})
    assert r.status_code == 200
    body = text(r)
    assert "Permanently closed (1)" in body and "brackets-cafe: Brackets [Cafe]: CLOSED_PERMANENTLY" in body
    assert "Temporarily closed (1)" in body and "draft-place: Draft Place: CLOSED_TEMPORARILY" in body
    assert "3 places audited, 2 without a place_id (cannot be audited), 1 already marked closed (skipped)." in body
    assert "Marked" not in body
    assert "ChIJgoneplace0004" not in seen and sorted(seen) == sorted(["ChIJtestplace0001", "ChIJbrackets0002", "ChIJdraftplace005"])
    assert row(client, "brackets-cafe")["closed"] is False
    run = recent(client)[0]
    assert run["kind"] == "audit" and run["scope"] == "all" and run["by_email"] == "dev@localhost"
    assert run["summary"] == (
        "3 audited, 2 without place_id; permanently closed: brackets-cafe; temporarily closed: draft-place"
    )
    assert run["details"]["Permanently closed"] == ["brackets-cafe: Brackets [Cafe]: CLOSED_PERMANENTLY"]

    with client.engine.begin() as conn:
        day = runs.last(conn, "audit").astimezone().date()
    page = client.get("/sync").text
    assert f"Last audit: {day.isoformat()} (0 days ago)" in page
    assert "audit" in page and "permanently closed: brackets-cafe" in page and "No runs yet" not in page


def test_audit_mark_closed(client, monkeypatch):
    fake_statuses(monkeypatch)
    r = client.post("/sync/audit", data={"mark_closed": "1"})
    assert r.status_code == 200
    assert "Marked 1 place(s) closed:" in r.text and 'href="/places/brackets-cafe"' in r.text
    closed = row(client, "brackets-cafe")
    assert closed["closed"] is True and repo.is_dirty(closed)
    assert row(client, "draft-place")["closed"] is False
    assert recent(client)[0]["summary"] == (
        "3 audited, 2 without place_id; permanently closed: brackets-cafe (marked closed); "
        "temporarily closed: draft-place"
    )


def test_audit_could_not_check(client, monkeypatch):
    fake_statuses(monkeypatch, fail_ids={"ChIJtestplace0001"})
    r = client.post("/sync/audit", data={})
    assert r.status_code == 200
    assert "Could not check (1)" in r.text and "test-place: Test Place: quota" in r.text
    assert recent(client)[0]["summary"].endswith("; could not check: test-place")


def test_all_operational(client, monkeypatch):
    monkeypatch.setattr(sync_routes, "get_place", lambda pid, **k: LION)
    r = client.post("/sync/audit", data={})
    assert "All 3 audited places are OPERATIONAL." in r.text
    assert recent(client)[0]["summary"] == (
        "3 audited, 2 without place_id; permanently closed: none; temporarily closed: none"
    )


# --- auth ---


def test_auth(make_client):
    client = make_client(admin_email="me@example.com")
    for path in ("/sync", "/places/test-place/sync"):
        assert client.get(path).status_code == 403
        assert client.get(path, headers=IAP).status_code == 200
