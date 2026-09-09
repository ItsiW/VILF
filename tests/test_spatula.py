"""Offline tests for the spatula command and its helpers (scripts/spatula.py)."""

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from PIL import Image

import scripts.places as places
import scripts.spatula as spatula
from scripts.places import CONTACT_FIELDS, parse_place
from scripts.schema import load_place, validate_place, write_place
from scripts.spatula import (
    BOLD_PROBLEM,
    find_duplicate,
    place_to_meta,
    query_from_maps_url,
    save_photo,
    scrape_and_gen_md,
    slugify,
    unique_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "places"


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


def test_unique_path(tmp_path):
    d = tmp_path / "p"
    assert unique_path(d, "foo") == d / "foo.md"
    assert d.is_dir()
    (d / "foo.md").touch()
    assert unique_path(d, "foo") == d / "foo-0.md"
    (d / "foo-0.md").touch()
    assert unique_path(d, "foo") == d / "foo-1.md"
    # a trailing -N on the base is stripped before appending
    e = tmp_path / "q"
    e.mkdir()
    (e / "foo-3.md").touch()
    assert unique_path(e, "foo-3") == e / "foo-0.md"


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


def test_find_duplicate(tmp_path):
    base = {**place_to_meta(LION), **REVIEW}
    write_place(tmp_path / "a.md", {**base, "lat": 37.9, "lon": -122.5}, "\n**x**\n")
    write_place(tmp_path / "b.md", {**base, "place_id": None, "lat": 37.8062}, "\n**x**\n")  # ~11 m away
    (tmp_path / "junk.md").write_text("no frontmatter here")
    assert find_duplicate({**base, "lat": 0.0, "lon": 0.0}, tmp_path) == tmp_path / "a.md"
    assert find_duplicate({**base, "place_id": "new"}, tmp_path) == tmp_path / "b.md"
    assert find_duplicate({**base, "place_id": "new", "lat": 37.7, "lon": -122.4}, tmp_path) is None


def test_spatula_end_to_end(tmp_path, monkeypatch):
    search = fake_search(SEARCH)
    monkeypatch.setattr(spatula, "search_text", search)
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(
        scrape_and_gen_md,
        ["-s", "Lion Dance Cafe", "--directory", str(tmp_path)],
        input="1\nThai\nDowntown Oakland\ny\n2\n1\nnot-a-date\n2024-03-31\n",
    )
    assert result.exit_code == 0, result.output
    assert search.queries == ["Lion Dance Cafe"]
    path = tmp_path / "lion-dance-cafe.md"
    meta, body = load_place(path)
    assert meta["cuisine"] == "Thai"
    assert meta["area"] == "Downtown Oakland"
    assert meta["drinks"] is True
    assert meta["taste"] == 2
    assert meta["value"] == 1
    assert meta["visited"] == "2024-03-31"
    assert meta["phone"] == "+15105550199"
    assert meta["website"] == "https://example.com/lion-dance"
    assert meta["city"] == "Oakland"
    assert meta["place_id"] == "ChIJfixtureLionDance"
    assert body == "\n<REVIEW>\n"
    assert validate_place(meta, body, "lion-dance-cafe") == [BOLD_PROBLEM]
    assert "lion-dance-cafe.md" in result.output
    assert "bold" in result.output


def test_spatula_no_prompt_skeleton(tmp_path, monkeypatch):
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lambda *a, **k: pytest.fail("get_place called"))
    result = runner.invoke(
        scrape_and_gen_md,
        ["-s", "x", "--no-prompt", "--no-details", "--city-as-area", "--directory", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    path = tmp_path / "lion-dance-cafe.md"
    text = path.read_text()
    for line in (
        "cuisine: \n",
        "drinks: \n",
        "visited: \n",
        "taste: \n",
        "area: Oakland\n",
        "phone: \n",
        "place_id: ChIJfixtureLionDance\n",
    ):
        assert line in text
    assert "website" not in text
    assert text.endswith("---\n\n<REVIEW>\n")
    meta, body = load_place(path)
    assert "cuisine: required" in validate_place(meta, body, path.stem)
    assert "To do" in result.output


def test_spatula_place_id(tmp_path, monkeypatch):
    calls = []

    def fake_get(place_id, fields=None):
        calls.append((place_id, fields))
        return LION

    monkeypatch.setattr(spatula, "get_place", fake_get)
    monkeypatch.setattr(spatula, "search_text", lambda *a, **k: pytest.fail("search called"))
    result = runner.invoke(
        scrape_and_gen_md, ["--place-id", "X", "--no-prompt", "--directory", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert calls == [("X", CONTACT_FIELDS)]
    assert (tmp_path / "lion-dance-cafe.md").exists()


def test_spatula_maps_url_and_retry(tmp_path, monkeypatch):
    search = fake_search([], [SEARCH[0]])
    monkeypatch.setattr(spatula, "search_text", search)
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(
        scrape_and_gen_md,
        ["-s", MAPS_URL, "--no-prompt", "--directory", str(tmp_path)],
        input="Lion Dance Cafe Oakland\n",
    )
    assert result.exit_code == 0, result.output
    assert search.queries == ["Lion Dance Café", "Lion Dance Cafe Oakland"]
    assert "No results" in result.output


def test_spatula_duplicate_aborts(tmp_path, monkeypatch):
    existing = {**place_to_meta(LION), **REVIEW, "lat": 37.9, "lon": -122.5}
    write_place(tmp_path / "existing.md", existing, "\n**x**\n")
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    args = ["-s", "x", "--no-prompt", "--directory", str(tmp_path)]
    result = runner.invoke(scrape_and_gen_md, args)
    assert result.exit_code != 0
    assert "existing.md" in result.output
    assert not (tmp_path / "lion-dance-cafe.md").exists()

    result = runner.invoke(scrape_and_gen_md, args + ["--force"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "lion-dance-cafe.md").exists()


def test_spatula_ask_first_declined(tmp_path, monkeypatch):
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(
        scrape_and_gen_md,
        ["-s", "x", "--no-prompt", "--ask-first", "--directory", str(tmp_path)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Not writing" in result.output
    assert list(tmp_path.glob("*.md")) == []


def test_spatula_photo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Image.new("RGB", (40, 20), "red").save("pic.png")
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(
        scrape_and_gen_md,
        ["-s", "x", "--photo", "pic.png", "--no-prompt", "--directory", "places"],
    )
    assert result.exit_code == 0, result.output
    out = Path("raw/food/lion-dance-cafe.jpg")
    assert out.exists()
    assert Image.open(out).format == "JPEG"
    assert "wider than 16:9" in result.output
    assert Path("places/lion-dance-cafe.md").exists()


def test_spatula_bad_photo_aborts_before_writing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("not-really.png").write_bytes(b"<html>not an image</html>")
    monkeypatch.setattr(spatula, "search_text", single())
    monkeypatch.setattr(spatula, "get_place", lion)
    result = runner.invoke(
        scrape_and_gen_md,
        ["-s", "x", "--photo", "not-really.png", "--directory", "places"],
        input="Thai\n",  # never reached: the photo is decoded before the prompts
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "cannot decode photo not-really.png" in result.output
    assert "cuisine" not in result.output
    assert list(Path("places").glob("*.md")) == []  # unique_path made the dir, nothing else
    assert not Path("raw").exists()


def test_save_photo_rules(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    Image.new("RGB", (16, 9), "blue").save("src.jpg")
    data = Path("src.jpg").read_bytes()
    dest = save_photo("src.jpg", "slug")
    assert dest == Path("raw/food/slug.jpg")
    assert dest.read_bytes() == data  # .jpg sources are copied byte-for-byte
    assert "Warning" not in capsys.readouterr().out
    with pytest.raises(click.ClickException, match="--force"):
        save_photo("src.jpg", "slug")
    Image.new("RGB", (8, 8), "green").save("other.png")
    save_photo("other.png", "slug", force=True)
    assert dest.read_bytes() != data
    with pytest.raises(click.ClickException):
        save_photo("missing.png", "slug2")


def test_cli_registers_commands():
    from scripts.cli import cli

    assert set(cli.commands) == {"build", "spatula", "check", "audit", "enrich"}
