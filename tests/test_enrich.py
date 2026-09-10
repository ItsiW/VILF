"""Offline tests for the enrich command (scripts/enrich.py) and places.distance_m."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import scripts.enrich as enrich
import scripts.places as places
from scripts import repo
from scripts.config import settings
from scripts.db import init_db, make_engine
from scripts.enrich import enrich as enrich_cmd
from scripts.enrich import enrich_meta
from scripts.places import CONTACT_FIELDS, distance_m, parse_place

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "places"


def load(name):
    return json.loads((FIXTURES / name).read_text())


LION = parse_place(load("details_full.json"))  # CONTACT-level: website set
SEARCH = [parse_place(p) for p in load("search_text.json")["places"]]  # CORE-level
# SEARCH[0]: 'Lion Dance Cafe' / ChIJfixtureLionDance at 37.8061,-122.2683, city Oakland
# SEARCH[1]: 'Fixture Vegan Kitchen' / ChIJfixtureBerkeley at 37.871,-122.268 (~7 km north)

# A valid place matching SEARCH[0], without any of the new keys.
BASE = dict(
    name="Lion Dance Cafe",
    cuisine="Thai",
    address="380 17th St",
    area="Downtown Oakland",
    lat=37.8061,
    lon=-122.2683,
    phone="+15105550199",
    menu=None,
    drinks=True,
    visited="2024-03-31",
    taste=2,
    value=1,
    instagram_published=False,
    city=None,
    place_id=None,
    website=None,
)
# A `---` and trailing spaces prove the body is preserved verbatim.
BODY = "\nGreat **pad see ew**.  \n\n---\n\ntrailing line\n"

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(places, "_request", lambda *a, **k: pytest.fail("network call attempted"))


@pytest.fixture(autouse=True)
def api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    monkeypatch.setattr(places, "DOTENV_PATH", tmp_path / ".env")


@pytest.fixture(autouse=True)
def no_get_place(monkeypatch):
    """Without --contact the Enterprise details call must never happen."""
    monkeypatch.setattr(enrich, "get_place", lambda *a, **k: pytest.fail("get_place called"))


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/t.db"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("VILF_MEDIA_STORAGE", str(tmp_path / "media"))
    monkeypatch.setenv("VILF_SITE_STORAGE", str(tmp_path / "site"))
    settings.cache_clear()
    engine = make_engine(url)
    init_db(engine)
    yield engine
    settings.cache_clear()


def seed(engine, slug, **overrides):
    with engine.begin() as conn:
        repo.insert(conn, repo.meta_to_row({**BASE, **overrides}, BODY, slug=slug))
    return slug


def read(engine, slug):
    with engine.connect() as conn:
        return repo.get(conn, slug)


def fake_search(results):
    """A search_text stand-in returning one fixed list; queries recorded."""

    def search(query, max_results=5, fields=None):
        search.queries.append(query)
        return list(results)

    search.queries = []
    return search


def test_distance_m():
    assert distance_m(0, 0, 1, 0) == pytest.approx(111195, abs=1)
    assert distance_m(37.8061, -122.2683, 37.8062, -122.2683) == pytest.approx(11.1, abs=0.2)
    assert distance_m(37.8061, -122.2683, 37.8062, -122.2683) == distance_m(
        37.8062, -122.2683, 37.8061, -122.2683
    )
    assert distance_m(37.8061, -122.2683, 37.8061, -122.2683) == 0


def test_enrich_sets_place_id_and_city(db, monkeypatch):
    search = fake_search([SEARCH[0]])
    monkeypatch.setattr(enrich, "search_text", search)
    seed(db, "lion")
    result = runner.invoke(enrich_cmd, ["lion"])
    assert result.exit_code == 0, result.output
    assert search.queries == ["Lion Dance Cafe 380 17th St"]
    row = read(db, "lion")
    assert row["place_id"] == "ChIJfixtureLionDance"
    assert row["city"] == "Oakland"
    assert row["website"] is None
    for key in ("name", "address", "lat", "lon", "phone", "area", "taste", "value"):
        assert row[key] == BASE[key], key
    assert row["body"] == BODY
    assert repo.is_dirty(row)
    assert "updated    lion: place_id=ChIJfixtureLionDance, city=Oakland [0 m]" in result.output
    assert "1 files: 1 updated, 0 unchanged, 0 unresolved, 0 errors" in result.output
    assert "Unresolved" not in result.output


def test_enrich_far_candidate_unresolved(db, monkeypatch):
    # nearest is SEARCH[0] (~500 m), listed second so the nearest-not-first logic is exercised
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[1], SEARCH[0]]))
    seed(db, "lion", lat=37.8106)
    before = read(db, "lion")
    result = runner.invoke(enrich_cmd, ["lion"])
    assert result.exit_code == 0, result.output
    assert read(db, "lion") == before
    assert "unresolved" in result.output
    assert "Lion Dance Cafe" in result.output
    assert "500 m" in result.output
    assert "Unresolved (1)" in result.output
    assert "1 unresolved" in result.output


def test_enrich_no_results_unresolved(db, monkeypatch):
    # lat/lon are NOT NULL in the database, so only the no-results branch can happen on rows
    seed(db, "empty")
    seed(db, "other", name="Other", lat=37.9, phone=None)
    before = {slug: read(db, slug) for slug in ("empty", "other")}
    monkeypatch.setattr(enrich, "search_text", fake_search([]))
    result = runner.invoke(enrich_cmd, ["empty", "other"])
    assert result.exit_code == 0, result.output
    for slug, row in before.items():
        assert read(db, slug) == row
    lines = result.output.splitlines()
    assert any(l.startswith("unresolved") and "empty:" in l and "no search results" in l for l in lines)
    assert any(l.startswith("unresolved") and "other:" in l and "'Other 380 17th St'" in l for l in lines)
    assert "Unresolved (2)" in result.output
    assert "2 unresolved" in result.output


def test_enrich_dry_run(db, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    seed(db, "lion")
    before = read(db, "lion")
    result = runner.invoke(enrich_cmd, ["--dry-run", "lion"])
    assert result.exit_code == 0, result.output
    assert read(db, "lion") == before
    assert "updated" in result.output
    assert "place_id=ChIJfixtureLionDance" in result.output
    assert "dry run" in result.output
    assert "Unresolved" not in result.output


def test_enrich_skips_existing_place_id_unless_force(db, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", lambda *a, **k: pytest.fail("search called"))
    seed(db, "lion", place_id="OLD", city="Elsewhere")
    before = read(db, "lion")
    result = runner.invoke(enrich_cmd, ["lion"])
    assert result.exit_code == 0, result.output
    assert read(db, "lion") == before
    assert "unchanged" in result.output
    assert "--force" in result.output

    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    result = runner.invoke(enrich_cmd, ["--force", "lion"])
    assert result.exit_code == 0, result.output
    row = read(db, "lion")
    assert row["place_id"] == "ChIJfixtureLionDance"
    assert row["city"] == "Oakland"
    assert row["body"] == BODY
    assert "updated" in result.output


def test_enrich_contact_fills_website_only_when_absent(db, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    calls = []

    def fake_get(place_id, fields=None):
        calls.append((place_id, fields))
        return LION

    monkeypatch.setattr(enrich, "get_place", fake_get)
    seed(db, "a")
    seed(db, "b", name="B Cafe", lat=37.8062, phone=None, website="https://keep.example")  # ~11 m away
    # both resolve to the same Google place; the second one hits the UNIQUE place_id rule
    result = runner.invoke(enrich_cmd, ["--contact", "a", "b"])
    assert result.exit_code == 0, result.output
    assert calls == [("ChIJfixtureLionDance", CONTACT_FIELDS)]
    assert read(db, "a")["website"] == "https://example.com/lion-dance"
    row_b = read(db, "b")
    assert row_b["website"] == "https://keep.example" and row_b["place_id"] is None
    assert "error      b: place_id ChIJfixtureLionDance already used by a" in result.output
    assert "1 updated" in result.output and "1 errors" in result.output


def test_enrich_name_difference_is_informational(db, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    seed(db, "lion", name="Lion Dance Café")
    result = runner.invoke(enrich_cmd, ["lion"])
    assert result.exit_code == 0, result.output
    assert "updated" in result.output
    assert "Google name: 'Lion Dance Cafe'" in result.output
    row = read(db, "lion")
    assert row["name"] == "Lion Dance Café"
    assert row["place_id"] == "ChIJfixtureLionDance"


def test_enrich_missing_api_key_exits_1(db, monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(enrich, "search_text", lambda *a, **k: pytest.fail("search called"))
    seed(db, "lion")
    result = runner.invoke(enrich_cmd, ["lion"])
    assert result.exit_code == 1
    assert "Missing Google Places API key" in result.output


def test_enrich_no_args_enriches_all_rows(db, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    seed(db, "lion")
    seed(db, "linked", name="Linked", lat=37.9, phone=None, place_id="OLD")
    result = runner.invoke(enrich_cmd, [])
    assert result.exit_code == 0, result.output
    assert "2 files: 1 updated, 1 unchanged" in result.output
    assert read(db, "lion")["place_id"] == "ChIJfixtureLionDance"
    result = runner.invoke(enrich_cmd, ["nope"])
    assert result.exit_code == 1 and "unknown slug 'nope'" in result.output


def test_enrich_no_rows(db):
    result = runner.invoke(enrich_cmd, [])
    assert result.exit_code == 0 and "No files to enrich." in result.output


def test_cli_registers_enrich():
    from scripts.cli import cli

    assert "enrich" in cli.commands


# --- pure core: enrich_meta (search/get passed explicitly; the autouse no_get_place fixture
# proves the module-level get_place is never reached) ---


def no_search(*a, **k):
    pytest.fail("search called")


def no_get(*a, **k):
    pytest.fail("get called")


def test_enrich_meta_updated():
    search = fake_search([SEARCH[0]])
    before = dict(BASE)
    status, detail, changes = enrich_meta(BASE, search=search, get=no_get)
    assert status == "updated"
    assert detail == "place_id=ChIJfixtureLionDance, city=Oakland [0 m]"
    assert changes == {"place_id": "ChIJfixtureLionDance", "city": "Oakland"}
    assert search.queries == ["Lion Dance Cafe 380 17th St"]
    assert BASE == before  # never mutated


def test_enrich_meta_unresolved():
    # nearest is SEARCH[0] (~500 m), listed second so the nearest-not-first logic is exercised
    status, detail, changes = enrich_meta(
        {**BASE, "lat": 37.8106}, search=fake_search([SEARCH[1], SEARCH[0]]), get=no_get
    )
    assert status == "unresolved"
    assert "'Lion Dance Cafe'" in detail and "500 m" in detail and "limit 150 m" in detail
    assert changes == {}
    status, detail, changes = enrich_meta(BASE, search=fake_search([]), get=no_get)
    assert (status, changes) == ("unresolved", {})
    assert detail == "no search results for 'Lion Dance Cafe 380 17th St'"
    status, detail, changes = enrich_meta({**BASE, "lat": None}, search=fake_search([SEARCH[0]]), get=no_get)
    assert status == "unresolved" and detail.startswith("no coordinates in file") and changes == {}


def test_enrich_meta_unchanged():
    status, detail, changes = enrich_meta({**BASE, "place_id": "OLD"}, search=no_search, get=no_get)
    assert (status, detail, changes) == ("unchanged", "already has a place_id (use --force to re-resolve)", {})
    linked = {**BASE, "place_id": "ChIJfixtureLionDance", "city": "Oakland"}
    status, detail, changes = enrich_meta(linked, search=fake_search([SEARCH[0]]), get=no_get, force=True)
    assert (status, detail, changes) == ("unchanged", "already up to date", {})


def test_enrich_meta_force():
    stale = {**BASE, "place_id": "OLD", "city": "Elsewhere"}
    status, detail, changes = enrich_meta(stale, search=fake_search([SEARCH[0]]), get=no_get, force=True)
    assert status == "updated"
    assert changes == {"place_id": "ChIJfixtureLionDance", "city": "Oakland"}
    # without force an existing city is kept even when Google's differs
    status, _, changes = enrich_meta({**BASE, "city": "Elsewhere"}, search=fake_search([SEARCH[0]]), get=no_get)
    assert status == "updated" and changes == {"place_id": "ChIJfixtureLionDance"}


def test_enrich_meta_contact():
    calls = []

    def get(place_id, fields=None):
        calls.append((place_id, fields))
        return LION

    status, detail, changes = enrich_meta(BASE, search=fake_search([SEARCH[0]]), get=get, contact=True)
    assert status == "updated"
    assert calls == [("ChIJfixtureLionDance", CONTACT_FIELDS)]
    assert changes["website"] == LION.website
    assert "website=https://example.com/lion-dance" in detail
    # a website already in the file is kept and costs no details call
    calls.clear()
    status, _, changes = enrich_meta(
        {**BASE, "website": "https://keep.example"}, search=fake_search([SEARCH[0]]), get=get, contact=True
    )
    assert calls == [] and "website" not in changes and status == "updated"
    # without contact the details call never happens
    enrich_meta(BASE, search=fake_search([SEARCH[0]]), get=no_get)


def test_enrich_meta_name_note():
    status, detail, changes = enrich_meta(
        {**BASE, "name": "Lion Dance Café"}, search=fake_search([SEARCH[0]]), get=no_get
    )
    assert status == "updated"
    assert detail.endswith(" (Google name: 'Lion Dance Cafe')")
    assert "name" not in changes


def test_enrich_meta_missing_name_raises():
    with pytest.raises(ValueError, match="missing name/address"):
        enrich_meta({**BASE, "name": None}, search=no_search, get=no_get)
