import html
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.routes.places as places_routes
from app.main import create_app
from scripts import repo
from scripts.config import Settings
from scripts.places import PlacesError, parse_place

FIXTURES = Path(__file__).parent / "fixtures"
ROWS = json.loads((FIXTURES / "snapshot.json").read_text())
LION = parse_place(json.loads((FIXTURES / "places" / "details_full.json").read_text()))
SEARCH = [parse_place(p) for p in json.loads((FIXTURES / "places" / "search_text.json").read_text())["places"]]

IAP = {"X-Goog-IAP-JWT-Assertion": "jwt", "X-Goog-Authenticated-User-Email": "accounts.google.com:me@example.com"}


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
        monkeypatch.setattr(places_routes, "search_text", lambda q, **k: SEARCH)
        monkeypatch.setattr(places_routes, "get_place", lambda pid, **k: LION)
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


# --- skeleton ---


def test_healthz_and_home(client):
    assert client.get("/healthz").json() == {"ok": True}
    r = client.get("/")
    assert r.status_code == 302 and r.headers["location"] == "/places"


def test_static_assets(client):
    assert client.get("/static/htmx.min.js").status_code == 200
    assert "text/css" in client.get("/static/admin.css").headers["content-type"]


# --- list ---


def test_list_shows_every_place(client):
    html = client.get("/places").text
    for r in ROWS:
        assert r["name"] in html
        assert f'href="/places/{r["slug"]}"' in html
    assert "<nav>" in html and "dev@localhost" in html


def test_list_filters_and_search(client):
    html = client.get("/places?filter=closed").text
    assert "Gone Place" in html and "Test Place" not in html
    html = client.get("/places?filter=dirty").text
    assert "Bare Place" in html and "Draft Place" in html and "Test Place" not in html
    html = client.get("/places?filter=nophoto").text
    assert "Draft Place" in html and "Test Place" not in html
    html = client.get("/places?q=thai").text
    assert "Test Place" in html and "Brackets [Cafe]" in html and "Bare Place" not in html
    assert client.get("/places?filter=bogus").status_code == 200


def test_list_partial_for_htmx(client):
    html = client.get("/places?q=thai", headers={"HX-Request": "true"}).text
    assert "<nav>" not in html and 'id="table"' in html and "Test Place" in html


# --- new: lookup, pick, create ---


def test_new_page(client):
    html = client.get("/places/new").text
    assert 'hx-post="/places/new/search"' in html
    assert '<div id="form" hidden>' in html
    assert "Fill in by hand" in html
    assert date.today().isoformat() in html


def test_search_lists_candidates_and_flags_duplicates(client):
    html = client.post("/places/new/search", data={"q": "lion"}).text
    assert "Lion Dance Cafe" in html and "Fixture Vegan Kitchen" in html
    assert "380 17th St" in html and "Oakland" in html and "OPERATIONAL" in html
    assert 'hx-post="/places/new/pick"' in html
    assert "already reviewed" not in html
    update(client, "draft-place", {"place_id": "ChIJfixtureLionDance"})
    html = client.post("/places/new/search", data={"q": "lion"}).text
    assert "already reviewed as draft-place" in html


def test_search_decodes_maps_url_and_reports_errors(client, monkeypatch):
    seen = []
    monkeypatch.setattr(places_routes, "search_text", lambda q, **k: seen.append(q) or SEARCH)
    client.post("/places/new/search", data={"q": "https://www.google.com/maps/place/Lion+Dance+Caf%C3%A9/@37.8,-122.2,17z"})
    assert seen == ["Lion Dance Café"]

    def boom(q, **k):
        raise PlacesError("Places API 403: key missing")

    monkeypatch.setattr(places_routes, "search_text", boom)
    r = client.post("/places/new/search", data={"q": "lion"})
    assert r.status_code == 200 and "Places API 403: key missing" in r.text


def test_pick_prefills_form(make_client):
    client = make_client(google_maps_embed_api_key="k")
    html = client.post("/places/new/pick", data={"place_id": "ChIJfixtureLionDance"}).text
    assert '<div id="form" >' in html or '<div id="form">' in html
    for value in ["Lion Dance Cafe", "380 17th St", "37.8061", "-122.2683", "+15105550199",
                  "https://example.com/lion-dance", "Oakland", "ChIJfixtureLionDance"]:
        assert f'value="{value}"' in html
    assert f'name="visited" value="{date.today().isoformat()}"' in html
    assert "<iframe" in html and "key=k&q=place_id:ChIJfixtureLionDance" in html
    assert 'href="https://maps.google.com/?cid=1"' in html and 'rel="noopener"' in html


def test_pick_without_embed_key(client):
    html = client.post("/places/new/pick", data={"place_id": "ChIJfixtureLionDance"}).text
    assert "<iframe" not in html and "GOOGLE_MAPS_EMBED_API_KEY" in html


def test_create_redirects_and_inserts(client):
    r = client.post("/places", data=FORM)
    assert r.status_code == 303 and r.headers["location"] == "/places/lion-dance-cafe?flash=created"
    created = row(client, "lion-dance-cafe")
    assert created["name"] == "Lion Dance Cafe" and created["lat"] == 37.8061 and created["taste"] == 3
    assert created["drinks"] is True and created["published_at"] is None
    assert "**laksa**" in created["body"]
    page = client.get(r.headers["location"]).text
    assert "Created" in page and "Lion Dance Cafe" in page


def test_create_with_street_in_slug_and_unique_slug(client):
    second = dict(FORM, name="Lion Dance Cafe Too", place_id="", lat="37.9", lon="-122.3",
                  phone="", menu="", website="", body="Second branch, **laksa** again.")
    r = client.post("/places", data=dict(second, street_in_slug="1"))
    assert r.headers["location"] == "/places/lion-dance-cafe-too-380-17th-st?flash=created"
    third = dict(second, name="Lion Dance Cafe Too", lat="37.91")
    # same name is refused; a different name that slugifies onto a taken slug gets a suffix
    assert client.post("/places", data=third).status_code == 422
    fourth = dict(second, name="Lion Dance Cafe Too!", lat="37.92", body="Third branch, **roti** this time.")
    r = client.post("/places", data=dict(fourth, street_in_slug="1"))
    assert r.headers["location"] == "/places/lion-dance-cafe-too-380-17th-st-0?flash=created"


def test_create_without_bold_dish_saves_with_warning(client):
    r = client.post("/places", data=dict(FORM, body="Draft, no dish yet."))
    assert r.status_code == 303
    page = client.get("/places/lion-dance-cafe").text
    assert "highlight a dish in bold" in page


def test_create_rejects_duplicate_name_and_place_id(client):
    r = client.post("/places", data=dict(FORM, name="Test Place"))
    assert r.status_code == 422 and "name 'Test Place' reused" in text(r)
    assert row(client, "test-place-0") is None
    update(client, "draft-place", {"place_id": "ChIJfixtureLionDance"})
    r = client.post("/places", data=FORM)
    assert r.status_code == 422 and "place_id 'ChIJfixtureLionDance' reused by draft-place" in text(r)
    assert row(client, "lion-dance-cafe") is None


def test_create_reports_bad_numbers_and_missing_fields(client):
    r = client.post("/places", data=dict(FORM, lat="north", taste=""))
    assert r.status_code == 422
    assert "lat: must be a number" in r.text and "taste: required" in r.text
    assert '<div id="form" >' in r.text or '<div id="form">' in r.text  # form stays open


# --- edit, save, delete ---


def test_edit_page(client):
    html = client.get("/places/test-place").text
    assert 'value="Test Place"' in html and 'name="slug" value="test-place" readonly' in html
    assert "published 2026-09-02" in html and 'name="closed"' in html and 'name="instagram_published"' in html
    assert 'href="https://www.google.com/maps/place/?q=place_id:ChIJtestplace0001"' in html
    assert 'hx-post="/places/test-place/relink"' in html
    assert 'hx-get="/places/test-place/photo"' in html
    assert 'hx-post="/places/test-place/delete"' not in html
    html = client.get("/places/draft-place").text
    assert 'hx-post="/places/draft-place/delete"' in html and ">dirty<" in html
    assert client.get("/places/nope").status_code == 404


def edit_form(client, slug, **changes):
    r = row(client, slug)
    meta, body = repo.row_to_meta(r)
    form = {k: ("" if v is None else str(v)) for k, v in meta.items() if not isinstance(v, bool)}
    for key in ("drinks", "closed", "instagram_published"):
        if meta[key]:
            form[key] = "1"
    form["body"] = body
    form.update(changes)
    return form


def test_save_updates_and_bumps_updated_at(client):
    before = row(client, "test-place")
    r = client.post("/places/test-place", data=edit_form(client, "test-place", cuisine="Lao", closed="1"))
    assert r.status_code == 200 and "Saved" in r.text and 'value="Lao"' in r.text
    after = row(client, "test-place")
    assert after["cuisine"] == "Lao" and after["closed"] is True and after["updated_at"] > before["updated_at"]
    assert after["photo_key"] == before["photo_key"] and after["published_at"] == before["published_at"]


def test_save_without_bold_warns_but_saves(client):
    r = client.post("/places/test-place", data=edit_form(client, "test-place", body="No dish here."))
    assert r.status_code == 200 and "Saved" in r.text and "highlight a dish in bold" in r.text
    assert row(client, "test-place")["body"] == "No dish here."


def test_save_rejects_bad_phone(client):
    r = client.post("/places/test-place", data=edit_form(client, "test-place", phone="123"))
    assert r.status_code == 422 and "phone: must look like" in r.text
    assert row(client, "test-place")["phone"] == "+14155551234"
    assert client.post("/places/nope", data=FORM).status_code == 404


def test_delete(client):
    r = client.post("/places/test-place/delete")
    assert r.status_code == 409 and "published" in r.text
    assert row(client, "test-place") is not None
    r = client.post("/places/draft-place/delete")
    assert r.status_code == 303 and r.headers["location"] == "/places"
    assert row(client, "draft-place") is None
    r = client.post("/places/bare-place/delete", headers={"HX-Request": "true"})
    assert r.status_code == 200 and r.headers["hx-redirect"] == "/places"
    assert client.post("/places/nope/delete").status_code == 404


# --- preview ---


def test_preview_renders_public_page(client):
    r = client.get("/places/test-place/preview")
    assert r.status_code == 200
    assert "Test Place" in r.text and "application/ld+json" in r.text and "pad thai" in r.text
    assert "https://vilf.org/places/test-place/" in r.text
    update(client, "draft-place", {"body": "No dish named yet."})
    r = client.get("/places/draft-place/preview")
    assert r.status_code == 422 and "highlight a dish in bold" in r.text


# --- relink ---


def test_relink_search_returns_candidates(client):
    html = client.post("/places/bare-place/relink", data={"q": "lion"}).text
    assert "Lion Dance Cafe" in html and 'action="/places/bare-place/relink"' in html
    assert 'name="place_id" value="ChIJfixtureLionDance"' in html
    assert client.post("/places/bare-place/relink", data={}).status_code == 400


def test_relink_updates_location_keeps_name(client):
    r = client.post("/places/bare-place/relink", data={"place_id": "ChIJfixtureLionDance"})
    assert r.status_code == 303 and r.headers["location"] == "/places/bare-place?flash=relinked"
    after = row(client, "bare-place")
    assert after["name"] == "Bare Place"
    assert after["place_id"] == "ChIJfixtureLionDance" and after["lat"] == 37.8061 and after["lon"] == -122.2683
    assert after["address"] == "380 17th St" and after["city"] == "Oakland"
    assert after["phone"] == "+15105550199" and after["website"] == "https://example.com/lion-dance"
    assert "Relinked" in client.get(r.headers["location"]).text


def test_relink_keeps_existing_phone_and_refuses_reused_place_id(client):
    client.post("/places/phone-only/relink", data={"place_id": "ChIJfixtureLionDance"})
    after = row(client, "phone-only")
    assert after["phone"] == "+15105550000" and after["place_id"] == "ChIJfixtureLionDance"
    r = client.post("/places/bare-place/relink", data={"place_id": "ChIJfixtureLionDance"})
    assert r.status_code == 422 and "place_id 'ChIJfixtureLionDance' reused by phone-only" in text(r)
    assert row(client, "bare-place")["place_id"] is None


# --- auth ---


def test_iap_headers(make_client):
    client = make_client(admin_email="me@example.com")
    assert client.get("/places").status_code == 403
    assert client.get("/places", headers={"X-Goog-Authenticated-User-Email": IAP["X-Goog-Authenticated-User-Email"]}).status_code == 403
    r = client.get("/places", headers=IAP)
    assert r.status_code == 200 and "me@example.com" in r.text
    other = dict(IAP, **{"X-Goog-Authenticated-User-Email": "accounts.google.com:you@example.com"})
    assert client.get("/places", headers=other).status_code == 403
    assert client.get("/media/x.jpg").status_code == 403
    assert client.get("/healthz").status_code == 200


def test_dev_user_without_admin_email(client):
    r = client.get("/places")
    assert r.status_code == 200 and "dev@localhost" in r.text
