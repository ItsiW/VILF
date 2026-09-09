"""Offline tests for the enrich command (scripts/enrich.py) and places.distance_m."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import scripts.enrich as enrich
import scripts.places as places
from scripts.enrich import enrich as enrich_cmd
from scripts.places import CONTACT_FIELDS, distance_m, parse_place
from scripts.schema import load_place, write_place

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "places"


def load(name):
    return json.loads((FIXTURES / name).read_text())


LION = parse_place(load("details_full.json"))  # CONTACT-level: website set
SEARCH = [parse_place(p) for p in load("search_text.json")["places"]]  # CORE-level
# SEARCH[0]: 'Lion Dance Cafe' / ChIJfixtureLionDance at 37.8061,-122.2683, city Oakland
# SEARCH[1]: 'Fixture Vegan Kitchen' / ChIJfixtureBerkeley at 37.871,-122.268 (~7 km north)

# A valid file matching SEARCH[0], without any of the new keys.
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


def write(directory, slug, **overrides):
    path = Path(directory) / f"{slug}.md"
    write_place(path, {**BASE, **overrides}, BODY)
    return path


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


def test_enrich_sets_place_id_and_city(tmp_path, monkeypatch):
    search = fake_search([SEARCH[0]])
    monkeypatch.setattr(enrich, "search_text", search)
    path = write(tmp_path, "lion")
    result = runner.invoke(enrich_cmd, [str(path)])
    assert result.exit_code == 0, result.output
    assert search.queries == ["Lion Dance Cafe 380 17th St"]
    meta, body = load_place(path)
    assert meta["place_id"] == "ChIJfixtureLionDance"
    assert meta["city"] == "Oakland"
    assert meta["website"] is None
    for key in ("name", "address", "lat", "lon", "phone", "area", "taste", "value"):
        assert meta[key] == BASE[key], key
    assert body == BODY
    assert path.read_text().endswith("---\n" + BODY)
    assert "updated" in result.output
    assert "1 updated" in result.output
    assert "Unresolved" not in result.output


def test_enrich_far_candidate_unresolved(tmp_path, monkeypatch):
    # nearest is SEARCH[0] (~500 m), listed second so the nearest-not-first logic is exercised
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[1], SEARCH[0]]))
    path = write(tmp_path, "lion", lat=37.8106)
    before = path.read_bytes()
    result = runner.invoke(enrich_cmd, [str(path)])
    assert result.exit_code == 0, result.output
    assert path.read_bytes() == before
    assert "unresolved" in result.output
    assert "Lion Dance Cafe" in result.output
    assert "500 m" in result.output
    assert "Unresolved (1)" in result.output
    assert "1 unresolved" in result.output


def test_enrich_no_results_or_coordinates_unresolved(tmp_path, monkeypatch):
    empty = write(tmp_path, "empty")
    nolat = write(tmp_path, "nolat", lat=None)
    before = {p: p.read_bytes() for p in (empty, nolat)}
    # first call (empty.md) gets no results, second (nolat.md) gets a candidate
    calls = []

    def search(query, max_results=5, fields=None):
        calls.append(query)
        return [] if len(calls) == 1 else [SEARCH[0]]

    monkeypatch.setattr(enrich, "search_text", search)
    result = runner.invoke(enrich_cmd, [str(empty), str(nolat)])
    assert result.exit_code == 0, result.output
    for p, data in before.items():
        assert p.read_bytes() == data
    lines = result.output.splitlines()
    assert any(l.startswith("unresolved") and "empty.md" in l and "no search results" in l for l in lines)
    assert any(
        l.startswith("unresolved") and "nolat.md" in l and "no coordinates" in l and "Lion Dance Cafe" in l
        for l in lines
    )
    assert "Unresolved (2)" in result.output
    assert "2 unresolved" in result.output


def test_enrich_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    path = write(tmp_path, "lion")
    before = path.read_bytes()
    result = runner.invoke(enrich_cmd, ["--dry-run", str(path)])
    assert result.exit_code == 0, result.output
    assert path.read_bytes() == before
    assert "updated" in result.output
    assert "place_id=ChIJfixtureLionDance" in result.output
    assert "dry run" in result.output
    assert "Unresolved" not in result.output


def test_enrich_skips_existing_place_id_unless_force(tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", lambda *a, **k: pytest.fail("search called"))
    path = write(tmp_path, "lion", place_id="OLD", city="Elsewhere")
    before = path.read_bytes()
    result = runner.invoke(enrich_cmd, [str(path)])
    assert result.exit_code == 0, result.output
    assert path.read_bytes() == before
    assert "unchanged" in result.output
    assert "--force" in result.output

    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    result = runner.invoke(enrich_cmd, ["--force", str(path)])
    assert result.exit_code == 0, result.output
    meta, body = load_place(path)
    assert meta["place_id"] == "ChIJfixtureLionDance"
    assert meta["city"] == "Oakland"
    assert body == BODY
    assert "updated" in result.output


def test_enrich_contact_fills_website_only_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    calls = []

    def fake_get(place_id, fields=None):
        calls.append((place_id, fields))
        return LION

    monkeypatch.setattr(enrich, "get_place", fake_get)
    a = write(tmp_path, "a")
    b = write(tmp_path, "b", website="https://keep.example")
    result = runner.invoke(enrich_cmd, ["--contact", str(a), str(b)])
    assert result.exit_code == 0, result.output
    assert calls == [("ChIJfixtureLionDance", CONTACT_FIELDS)]
    assert load_place(a)[0]["website"] == "https://example.com/lion-dance"
    meta_b, body_b = load_place(b)
    assert meta_b["website"] == "https://keep.example"
    assert meta_b["place_id"] == "ChIJfixtureLionDance"
    assert body_b == BODY
    assert "2 updated" in result.output


def test_enrich_malformed_files_reported_and_run_continues(tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    (tmp_path / "01-bad.md").write_text("---\nname: [unclosed\n---\n")
    (tmp_path / "02-noname.md").write_text("---\naddress: 380 17th St\nlat: 1\nlon: 2\n---\n")
    (tmp_path / "03-text.md").write_text("just text")
    good = write(tmp_path, "04-good")
    # no FILES: the default-directory path, in sorted order
    result = runner.invoke(enrich_cmd, ["--directory", str(tmp_path)])
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    errors = [l for l in lines if l.startswith("error")]
    assert len(errors) == 3
    assert "01-bad.md" in errors[0] and "flow sequence" in errors[0]
    assert "02-noname.md" in errors[1] and "missing name" in errors[1]
    assert "03-text.md" in errors[2] and "no leading frontmatter" in errors[2]
    assert any(l.startswith("updated") and "04-good.md" in l for l in lines)
    assert load_place(good)[0]["place_id"] == "ChIJfixtureLionDance"
    assert "4 files" in result.output
    assert "3 errors" in result.output


def test_enrich_name_difference_is_informational(tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "search_text", fake_search([SEARCH[0]]))
    path = write(tmp_path, "lion", name="Lion Dance Café")
    result = runner.invoke(enrich_cmd, [str(path)])
    assert result.exit_code == 0, result.output
    assert "updated" in result.output
    assert "Google name: 'Lion Dance Cafe'" in result.output
    meta, _ = load_place(path)
    assert meta["name"] == "Lion Dance Café"
    assert meta["place_id"] == "ChIJfixtureLionDance"


def test_enrich_missing_api_key_exits_1(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(enrich, "search_text", lambda *a, **k: pytest.fail("search called"))
    path = write(tmp_path, "lion")
    result = runner.invoke(enrich_cmd, [str(path)])
    assert result.exit_code == 1
    assert "Missing Google Places API key" in result.output


def test_cli_registers_enrich():
    from scripts.cli import cli

    assert "enrich" in cli.commands
