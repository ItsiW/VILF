"""Offline tests for the spatula command and its helpers (scripts/spatula.py)."""

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest
import requests
from click.testing import CliRunner
from PIL import Image

import scripts.places as places
import scripts.spatula as spatula
from scripts import repo
from scripts.config import settings
from scripts.db import init_db, make_engine
from scripts.places import CONTACT_FIELDS, parse_place
from scripts.schema import validate_place
from scripts.spatula import (
    BODY,
    BOLD_PROBLEM,
    find_duplicate,
    place_to_meta,
    query_from_maps_url,
    scrape_and_gen_md,
    slugify,
    unique_name,
)
from scripts.storage import LocalStorage

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "places"
HAVE_PHOTOS = importlib.util.find_spec("scripts.photos") is not None


def load(name):
    return json.loads((FIXTURES / name).read_text())


LION = parse_place(load("details_full.json"))  # CONTACT-level: phone and website set
SEARCH = [parse_place(p) for p in load("search_text.json")["places"]]  # CORE-level
MAPS_URL = "https://www.google.com/maps/place/Lion+Dance+Caf%C3%A9/@37.8060737,-122.270113,17z/data=!3m1"
REVIEW = dict(cuisine="Thai", area="Downtown Oakland", drinks=True, visited="2024-03-31", taste=2, value=1)

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(places, "_request", lambda *a, **k: pytest.fail("network call attempted"))


def _repo_files():
    return {p.name for d in ("places", "raw/food") for p in (REPO_ROOT / d).glob("*")}


@pytest.fixture(autouse=True)
def repo_untouched():
    """Belt and braces: no test may add or remove files in the real places/ or raw/food/."""
    before = _repo_files()
    yield
    assert _repo_files() == before


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


def seed(engine, slug, meta, body="\n**x**\n"):
    with engine.begin() as conn:
        repo.insert(conn, repo.meta_to_row(meta, body, slug=slug))


def rows(engine):
    with engine.connect() as conn:
        return {r["slug"]: r for r in repo.all_rows(conn)}


def fake_search(*results_per_call):
    """A search_text stand-in: one result list per call (the last repeats), queries recorded."""
    remaining = list(results_per_call)

    def search(query, max_results=5, fields=None):
        search.queries.append(query)
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    search.queries = []
    return search


def single():
    return fake_search([SEARCH[0]])


def lion(place_id, fields=None):
    return LION


def test_slugify():
    assert slugify("Café") == "cafe"
    assert slugify("Azalina's") == "azalinas"
    assert slugify("Ladle & Leaf") == "ladle-leaf"
    assert slugify("St. John's, Pizza") == "st-johns-pizza"
    assert slugify("Lion Dance Cafe", "380 17th St") == "lion-dance-cafe-380-17th-st"


def test_query_from_maps_url():
    assert query_from_maps_url(MAPS_URL) == "Lion Dance Café"
    assert query_from_maps_url("Lion Dance Cafe Oakland") is None
    assert query_from_maps_url("https://maps.google.com/?cid=1") is None


def test_place_to_meta():
    assert place_to_meta(LION) == {
        "name": "Lion Dance Cafe",
        "cuisine": None,
        "address": "380 17th St",
        "area": None,
        "lat": 37.8061,
        "lon": -122.2683,
        "phone": "+15105550199",
        "menu": None,
        "drinks": None,
        "visited": None,
        "taste": None,
        "value": None,
        "instagram_published": False,
        "city": "Oakland",
        "place_id": "ChIJfixtureLionDance",
        "website": "https://example.com/lion-dance",
    }
    assert place_to_meta(LION, city_as_area=True)["area"] == "Oakland"
    core = place_to_meta(SEARCH[0])
    assert core["website"] is None
    assert core["phone"] is None


def test_find_duplicate_rows():
    meta = place_to_meta(LION)  # ChIJfixtureLionDance at 37.8061, -122.2683
    far_same_id = {"slug": "a", "place_id": "ChIJfixtureLionDance", "lat": 37.9, "lon": -122.5}
    near_no_id = {"slug": "b", "place_id": None, "lat": 37.8062, "lon": -122.2683}  # ~11 m away
    unrelated = {"slug": "c", "place_id": "other", "lat": 37.7, "lon": -122.4}
    assert find_duplicate({**meta, "lat": 0.0, "lon": 0.0}, [unrelated, far_same_id]) == "a"
    assert find_duplicate({**meta, "place_id": "new"}, [far_same_id, near_no_id]) == "b"
    assert find_duplicate({**meta, "place_id": "new"}, [unrelated, far_same_id]) is None
    assert find_duplicate(meta, []) is None
    # the first hit wins, in row order
    assert find_duplicate(meta, [near_no_id, far_same_id]) == "b"
    # rows without numeric coordinates only ever match on place_id
    for bad in (None, "37.8062", True):
        assert find_duplicate({**meta, "place_id": "new"}, [{**near_no_id, "lat": bad}]) is None
    # a meta without place_id never matches on id, even against a row with place_id None
    assert find_duplicate({**meta, "place_id": None, "lat": 0.0, "lon": 0.0}, [near_no_id]) is None
    # rows may be any iterable
    assert find_duplicate(meta, iter([near_no_id])) == "b"


def test_unique_name():
    seen = []

    def exists(name):
        seen.append(name)
        return name in taken

    taken = set()
    assert unique_name("foo", exists) == "foo"
    assert seen == ["foo"]
    taken = {"foo"}
    assert unique_name("foo", exists) == "foo-0"
    taken = {"foo", "foo-0"}
    assert unique_name("foo", exists) == "foo-1"
    # a trailing -N on the base is stripped before appending; the base itself is tried first
    taken = {"foo-3"}
    seen.clear()
    assert unique_name("foo-3", exists) == "foo-0"
    assert seen == ["foo-3", "foo-0"]
    assert unique_name("bar-7", exists) == "bar-7"


def test_spatula_end_to_end(db, monkeypatch):
    search = fake_search(SEARCH)
    monkeypatch.setattr(spatula, "search_text", search)
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(
        scrape_and_gen_md,
        ["-s", "Lion Dance Cafe"],
        input="1\nThai\nDowntown Oakland\ny\n2\n1\nnot-a-date\n2024-03-31\n",
    )
    assert result.exit_code == 0, result.output
    assert search.queries == ["Lion Dance Cafe"]
    row = rows(db)["lion-dance-cafe"]
    assert row["cuisine"] == "Thai"
    assert row["area"] == "Downtown Oakland"
    assert row["drinks"] is True
    assert row["taste"] == 2
    assert row["value"] == 1
    assert row["visited"] == "2024-03-31"
    assert row["phone"] == "+15105550199"
    assert row["website"] == "https://example.com/lion-dance"
    assert row["city"] == "Oakland"
    assert row["place_id"] == "ChIJfixtureLionDance"
    assert row["body"] == BODY == "\n<REVIEW>\n"
    assert row["photo_key"] is None
    assert repo.is_dirty(row)
    meta, body = repo.row_to_meta(row)
    assert validate_place(meta, body, "lion-dance-cafe") == [BOLD_PROBLEM]
    assert "Created lion-dance-cafe" in result.output
    assert "bold" in result.output


def test_spatula_no_prompt_placeholders(db, monkeypatch):
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lambda *a, **k: pytest.fail("get_place called"))
    result = runner.invoke(scrape_and_gen_md, ["-s", "x", "--no-prompt", "--no-details", "--city-as-area"])
    assert result.exit_code == 0, result.output
    row = rows(db)["lion-dance-cafe"]
    # the database requires these, so --no-prompt fills placeholders to replace later
    assert row["cuisine"] == "TBD" and row["area"] == "Oakland"
    assert (row["drinks"], row["taste"], row["value"]) == (False, 0, 0)
    assert row["visited"] == date.today().isoformat()
    assert row["phone"] is None and row["website"] is None
    assert row["place_id"] == "ChIJfixtureLionDance"
    assert row["body"] == BODY
    assert "To do" in result.output
    assert "placeholder area, cuisine, drinks, taste, value, visited values" in result.output
    assert "write the review" in result.output
    # without --city-as-area the area placeholder is still the city
    monkeypatch.setattr(spatula, "search_text", fake_search([SEARCH[1]]))
    result = runner.invoke(scrape_and_gen_md, ["-s", "x", "--no-prompt", "--no-details"])
    assert result.exit_code == 0, result.output
    assert rows(db)["fixture-vegan-kitchen"]["area"] == SEARCH[1].city


def test_spatula_place_id(db, monkeypatch):
    calls = []

    def fake_get(place_id, fields=None):
        calls.append((place_id, fields))
        return LION

    monkeypatch.setattr(spatula, "get_place", fake_get)
    monkeypatch.setattr(spatula, "search_text", lambda *a, **k: pytest.fail("search called"))
    result = runner.invoke(scrape_and_gen_md, ["--place-id", "X", "--no-prompt"])
    assert result.exit_code == 0, result.output
    assert calls == [("X", CONTACT_FIELDS)]
    assert "lion-dance-cafe" in rows(db)


def test_spatula_maps_url_and_retry(db, monkeypatch):
    search = fake_search([], [SEARCH[0]])
    monkeypatch.setattr(spatula, "search_text", search)
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(
        scrape_and_gen_md, ["-s", MAPS_URL, "--no-prompt"], input="Lion Dance Cafe Oakland\n"
    )
    assert result.exit_code == 0, result.output
    assert search.queries == ["Lion Dance Café", "Lion Dance Cafe Oakland"]
    assert "No results" in result.output
    assert "lion-dance-cafe" in rows(db)


def test_spatula_duplicate_aborts(db, monkeypatch):
    seed(db, "existing", {**place_to_meta(LION), **REVIEW, "name": "Existing", "lat": 37.9, "lon": -122.5, "phone": None})
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    args = ["-s", "x", "--no-prompt"]
    result = runner.invoke(scrape_and_gen_md, args)
    assert result.exit_code != 0
    assert "existing already covers this place" in result.output
    assert set(rows(db)) == {"existing"}

    # --force ignores the duplicate; the place_id is UNIQUE though, so that clash is reported
    result = runner.invoke(scrape_and_gen_md, args + ["--force"])
    assert result.exit_code != 0
    assert "place_id ChIJfixtureLionDance already used by existing" in result.output
    assert set(rows(db)) == {"existing"}


def test_spatula_force_and_unique_slug(db, monkeypatch):
    # same name and slug, different place and coordinates: --force writes lion-dance-cafe-0
    seed(db, "lion-dance-cafe", {**place_to_meta(LION), **REVIEW, "name": "Lion Dance Cafe (Berkeley)", "place_id": "OTHER", "lat": 37.9, "lon": -122.5, "phone": None})
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(scrape_and_gen_md, ["-s", "x", "--no-prompt", "--force"])
    assert result.exit_code == 0, result.output
    assert "Created lion-dance-cafe-0" in result.output
    assert set(rows(db)) == {"lion-dance-cafe", "lion-dance-cafe-0"}


def test_spatula_name_clash_reported(db, monkeypatch):
    seed(db, "far", {**place_to_meta(LION), **REVIEW, "place_id": "FAR", "lat": 37.9, "lon": -122.5, "phone": None})
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(scrape_and_gen_md, ["-s", "x", "--no-prompt"])
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "name 'Lion Dance Cafe' reused by far and lion-dance-cafe" in result.output
    assert set(rows(db)) == {"far"}


def test_spatula_ask_first_declined(db, monkeypatch):
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(scrape_and_gen_md, ["-s", "x", "--no-prompt", "--ask-first"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Create lion-dance-cafe?" in result.output
    assert "Not writing" in result.output
    assert rows(db) == {}


def test_spatula_photo(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Image.new("RGB", (40, 20), "red").save("pic.png")
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(scrape_and_gen_md, ["-s", "x", "--photo", "pic.png", "--no-prompt"])
    assert result.exit_code == 0, result.output
    row = rows(db)["lion-dance-cafe"]
    media = LocalStorage(tmp_path / "media")
    if HAVE_PHOTOS:
        assert row["photo_key"] == "originals/lion-dance-cafe.jpg"
        assert (row["photo_width"], row["photo_height"]) == (40, 20)
        assert media.exists("originals/lion-dance-cafe.jpg")
        assert media.exists("img/food/lion-dance-cafe.webp")
    else:
        assert "Photo skipped" in result.output
        assert row["photo_key"] is None
        assert media.listing() == {}
    assert not Path("raw").exists()


def test_spatula_photo_url_failure_aborts(db, monkeypatch):
    def boom(url, **kw):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(spatula.requests, "get", boom)
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(
        scrape_and_gen_md, ["-s", "x", "--photo", "https://example.com/pic.jpg"], input="Thai\n"
    )
    assert result.exit_code == 1
    assert "cannot download photo https://example.com/pic.jpg" in result.output
    assert "cuisine" not in result.output
    assert rows(db) == {}


def test_spatula_bad_photo_aborts_before_writing(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("not-really.png").write_bytes(b"<html>not an image</html>")
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(
        scrape_and_gen_md,
        ["-s", "x", "--photo", "not-really.png"],
        input="Thai\n",  # never reached: the photo is decoded before the prompts
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "cannot decode photo not-really.png" in result.output
    assert "cuisine" not in result.output
    assert rows(db) == {}
    assert not Path("raw").exists()


def test_cli_registers_commands():
    from scripts.cli import cli

    assert set(cli.commands) == {"build", "spatula", "check", "audit", "enrich", "publish", "serve", "db"}
