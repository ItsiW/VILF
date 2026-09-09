"""Offline tests for the check (scripts/cross_reference.py) and audit (scripts/audit.py) commands."""

import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import scripts.audit as audit
import scripts.cross_reference as cross_reference
import scripts.places as places
from scripts.audit import audit_places
from scripts.cross_reference import cross_reference_md
from scripts.places import CONTACT_FIELDS, PlacesError, parse_place
from scripts.schema import write_place

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "places"


def load(name):
    return json.loads((FIXTURES / name).read_text())


LION = parse_place(load("details_full.json"))
SEARCH = [parse_place(p) for p in load("search_text.json")["places"]]

# A valid file that matches LION exactly.
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
    city="Oakland",
    place_id="ChIJfixtureLionDance",
    website=None,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(places, "_request", lambda *a, **k: pytest.fail("network call attempted"))


def write(directory, slug, **overrides):
    path = Path(directory) / f"{slug}.md"
    write_place(path, {**BASE, **overrides}, "\n**Dish**\n")
    return str(path)


def lion(place_id, fields=None):
    return LION


# --- check ---


def test_check_all_good(tmp_path, monkeypatch):
    monkeypatch.setattr(cross_reference, "get_place", lion)
    good = write(tmp_path, "good")
    result = runner.invoke(cross_reference_md, [good])
    assert result.exit_code == 0, result.output
    assert "✔ " + good in result.output
    assert "All files look good" in result.output


def test_check_mismatch_exit_1(tmp_path, monkeypatch):
    monkeypatch.setattr(cross_reference, "get_place", lion)
    queries = []

    def fake_search(query, max_results=5, fields=None):
        queries.append(query)
        return [SEARCH[0]]

    monkeypatch.setattr(cross_reference, "search_text", fake_search)
    good = write(tmp_path, "good")
    bad = write(tmp_path, "bad", lat=37.8161, place_id=None)
    result = runner.invoke(cross_reference_md, [good, bad])
    assert result.exit_code == 1
    assert "✔ " + good in result.output
    assert "✘ " + bad in result.output
    assert "matched by search" in result.output
    assert "Current latitude: 37.8161 | Determined latitude: 37.8061" in result.output
    assert queries == ["Lion Dance Cafe 380 17th St"]


def test_check_contact(tmp_path, monkeypatch):
    seen = {}

    def fake_get(place_id, fields=None):
        seen["fields"] = fields
        return LION

    monkeypatch.setattr(cross_reference, "get_place", fake_get)
    f = write(tmp_path, "contact", phone="+15105550100")
    result = runner.invoke(cross_reference_md, [f, "--contact"])
    assert seen["fields"] == CONTACT_FIELDS
    assert result.exit_code == 1
    assert (
        "Current phone number: +15105550100 | Determined phone number: +15105550199"
        in result.output
    )
    assert "Website (not in file): https://example.com/lion-dance" in result.output


def test_check_places_error(tmp_path, monkeypatch):
    def boom(place_id, fields=None):
        raise PlacesError("boom")

    monkeypatch.setattr(cross_reference, "get_place", boom)
    f = write(tmp_path, "err")
    result = runner.invoke(cross_reference_md, [f])
    assert result.exit_code == 1
    assert "✘ " + f in result.output
    assert "boom" in result.output


def test_check_bad_files_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(cross_reference, "get_place", lion)
    monkeypatch.setattr(
        cross_reference, "search_text", lambda *a, **k: pytest.fail("search called")
    )
    bad_yaml = tmp_path / "bad-yaml.md"
    bad_yaml.write_text("---\nname: [unclosed\nlat: 1\n---\n")
    no_name = tmp_path / "no-name.md"
    no_name.write_text("---\naddress: 380 17th St\nplace_id: X\n---\n")
    no_frontmatter = tmp_path / "plain.md"
    no_frontmatter.write_text("just text")
    good = write(tmp_path, "good")
    result = runner.invoke(
        cross_reference_md, [str(bad_yaml), str(no_name), str(no_frontmatter), good]
    )
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == 1
    for f in (bad_yaml, no_name, no_frontmatter):
        assert f"✘ {f}" in result.output
    assert "✔ " + good in result.output  # later files are still checked
    assert "missing name" in result.output
    assert "no leading frontmatter" in result.output
    assert "may need inspection" in result.output


def test_check_string_coordinate_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(cross_reference, "get_place", lion)
    quoted = tmp_path / "quoted-lat.md"
    quoted.write_text(
        "---\nname: Lion Dance Cafe\naddress: 380 17th St\n"
        'lat: "37.8061"\nlon: -122.2683\nplace_id: X\n---\n'
    )
    good = write(tmp_path, "good")
    result = runner.invoke(cross_reference_md, [str(quoted), good])
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == 1
    assert f"✘ {quoted}" in result.output
    assert "Current latitude: '37.8061' (not a number) | Determined latitude: 37.8061" in result.output
    assert "✔ " + good in result.output  # later files are still checked


def test_check_no_files():
    result = runner.invoke(cross_reference_md, [])
    assert result.exit_code == 0
    assert "No files to check." in result.output


# --- audit ---


def place_with_status(status):
    data = copy.deepcopy(load("details_full.json"))
    data["businessStatus"] = status
    return parse_place(data)


def test_audit_groups(tmp_path, monkeypatch):
    # the audit line prints the file's name, so each file gets the name asserted on below
    write(tmp_path, "open", name="Lion Dance Cafe", place_id="A")
    write(tmp_path, "closed", name="Shuttered Vegan Diner", place_id="B")
    write(tmp_path, "temp", name="Temp Cafe", place_id="C")
    write(tmp_path, "weird", name="Weird Cafe", place_id="D")
    write(tmp_path, "broken", name="Broken Cafe", place_id="E")
    write(tmp_path, "noid", name="No Id Cafe", place_id=None)
    responses = {
        "A": place_with_status("OPERATIONAL"),
        "B": parse_place(load("details_closed.json")),
        "C": place_with_status("CLOSED_TEMPORARILY"),
        "D": place_with_status("SOMETHING_NEW"),
    }

    def fake_get(place_id, fields=None):
        if place_id == "E":
            raise PlacesError("quota")
        return responses[place_id]

    monkeypatch.setattr(audit, "get_place", fake_get)
    result = runner.invoke(audit_places, ["--directory", str(tmp_path)])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Permanently closed (1):\n  closed: Shuttered Vegan Diner: CLOSED_PERMANENTLY" in out
    assert "Temporarily closed (1):\n  temp: Temp Cafe: CLOSED_TEMPORARILY" in out
    assert "Unknown status (1):\n  weird: Weird Cafe: SOMETHING_NEW" in out
    assert "Could not check (1):\n  broken: Broken Cafe: quota" in out
    assert not any(line.strip().startswith("open:") for line in out.splitlines())
    assert "5 places audited, 1 without a place_id" in out


def test_audit_bad_files_do_not_abort(tmp_path, monkeypatch):
    (tmp_path / "bad-yaml.md").write_text("---\nname: [unclosed\nplace_id: Z\n---\n")
    (tmp_path / "no-name.md").write_text("---\nplace_id: A\n---\n")
    write(tmp_path, "open", place_id="A")
    monkeypatch.setattr(audit, "get_place", lion)
    result = runner.invoke(audit_places, ["--directory", str(tmp_path)])
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    i = lines.index("Could not check (1):")
    # the multi-line YAML error is collapsed onto the one line for that place
    assert lines[i + 1].startswith("  bad-yaml: ") and "flow sequence" in lines[i + 1]
    assert lines[i + 2] == "2 places audited, 0 without a place_id (cannot be audited)."


def test_audit_all_operational(tmp_path, monkeypatch):
    write(tmp_path, "open", place_id="A")
    monkeypatch.setattr(audit, "get_place", lion)
    result = runner.invoke(audit_places, ["--directory", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "All 1 audited places are OPERATIONAL." in result.output
