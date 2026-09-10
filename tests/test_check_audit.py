"""Offline tests for the check (scripts/cross_reference.py) and audit (scripts/audit.py) commands."""

import copy
import json
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

import scripts.audit as audit
import scripts.cross_reference as cross_reference
import scripts.places as places
from scripts import repo, runs
from scripts.audit import AuditReport, audit_places, audit_rows
from scripts.config import settings
from scripts.cross_reference import CheckResult, check_place, cross_reference_md
from scripts.db import init_db, make_engine
from scripts.places import CONTACT_FIELDS, CORE_FIELDS, PlacesError, parse_place

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "places"


def load(name):
    return json.loads((FIXTURES / name).read_text())


LION = parse_place(load("details_full.json"))
SEARCH = [parse_place(p) for p in load("search_text.json")["places"]]

# A valid place that matches LION exactly.
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
BODY = "\n**Dish**\n"

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(places, "_request", lambda *a, **k: pytest.fail("network call attempted"))


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    """Every command opens settings().database_url: point it at a fresh SQLite file."""
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
    """Insert a BASE-like row; name, coordinates, phone and place_id are UNIQUE so vary them."""
    with engine.begin() as conn:
        repo.insert(conn, repo.meta_to_row({**BASE, **overrides}, BODY, slug=slug))
    return slug


def read(engine, slug):
    with engine.connect() as conn:
        return repo.get(conn, slug)


def recent(engine):
    with engine.connect() as conn:
        return runs.recent(conn)


def lion(place_id, fields=None):
    return LION


# --- check ---


def test_check_all_good(db, monkeypatch):
    monkeypatch.setattr(cross_reference, "get_place", lion)
    seed(db, "good")
    result = runner.invoke(cross_reference_md, ["good"])
    assert result.exit_code == 0, result.output
    assert "✔ good" in result.output
    assert "All files look good" in result.output


def test_check_mismatch_exit_1(db, monkeypatch):
    monkeypatch.setattr(cross_reference, "get_place", lion)
    queries = []

    def fake_search(query, max_results=5, fields=None):
        queries.append(query)
        return [SEARCH[0]]

    monkeypatch.setattr(cross_reference, "search_text", fake_search)
    seed(db, "good")
    seed(db, "bad", name="Bad Cafe", lat=37.8161, place_id=None, phone=None)
    result = runner.invoke(cross_reference_md, ["good", "bad"])
    assert result.exit_code == 1
    assert "✔ good" in result.output
    assert "✘ bad" in result.output
    assert "matched by search" in result.output
    assert "Current latitude: 37.8161 | Determined latitude: 37.8061" in result.output
    assert queries == ["Bad Cafe 380 17th St"]
    assert "The following files may need inspection:" in result.output


def test_check_contact(db, monkeypatch):
    seen = {}

    def fake_get(place_id, fields=None):
        seen["fields"] = fields
        return LION

    monkeypatch.setattr(cross_reference, "get_place", fake_get)
    seed(db, "contact", phone="+15105550100")
    result = runner.invoke(cross_reference_md, ["contact", "--contact"])
    assert seen["fields"] == CONTACT_FIELDS
    assert result.exit_code == 1
    assert (
        "Current phone number: +15105550100 | Determined phone number: +15105550199"
        in result.output
    )
    assert "Website (not in file): https://example.com/lion-dance" in result.output


def test_check_places_error(db, monkeypatch):
    def boom(place_id, fields=None):
        raise PlacesError("boom")

    monkeypatch.setattr(cross_reference, "get_place", boom)
    seed(db, "err")
    result = runner.invoke(cross_reference_md, ["err"])
    assert result.exit_code == 1
    assert "✘ err" in result.output
    assert "boom" in result.output


def test_check_unknown_slug(db, monkeypatch):
    monkeypatch.setattr(cross_reference, "get_place", lambda *a, **k: pytest.fail("get called"))
    seed(db, "good")
    result = runner.invoke(cross_reference_md, ["good", "nope"])
    assert result.exit_code == 1
    assert "unknown slug 'nope'" in result.output


def test_check_no_rows(db):
    result = runner.invoke(cross_reference_md, [])
    assert result.exit_code == 0
    assert "No files to check." in result.output


def test_check_no_args_checks_every_place(db, monkeypatch):
    seed(db, "one")
    seed(db, "two", name="Two", lat=37.9, phone=None, place_id="TWO")
    monkeypatch.setattr(cross_reference, "get_place", lion)
    result = runner.invoke(cross_reference_md, [])
    assert result.exit_code == 1, result.output
    assert "✔ one" in result.output and "✘ two" in result.output


def test_check_search_fallback_fetches_one_result(db, monkeypatch):
    seed(db, "unlinked", place_id=None)
    seen = {}

    def fake_search(query, **kw):
        seen.update(kw)
        return [LION]

    monkeypatch.setattr(cross_reference, "search_text", fake_search)
    result = runner.invoke(cross_reference_md, ["unlinked"])
    assert result.exit_code == 0, result.output
    assert seen["max_results"] == 1


def test_check_fix_applies_google_values(db, monkeypatch):
    seed(db, "lion", address="1 Wrong St", lat=37.9, lon=-122.0, phone="+15105550000", website=None)
    before = read(db, "lion")
    monkeypatch.setattr(cross_reference, "get_place", lion)
    result = runner.invoke(cross_reference_md, ["--contact", "--fix", "lion"])
    assert result.exit_code == 0, result.output
    assert "fixed: address, coordinates, phone, website" in result.output
    row = read(db, "lion")
    assert row["address"] == LION.street_address
    assert row["lat"] == round(LION.lat, 7) and row["lon"] == round(LION.lon, 7)
    assert row["phone"] == LION.phone and row["website"] == LION.website
    assert row["name"] == "Lion Dance Cafe" and row["body"] == BODY
    assert row["updated_at"] > before["updated_at"] and repo.is_dirty(row)
    r = recent(db)[0]
    assert r["kind"] == "check" and r["scope"] == "lion"
    assert r["summary"] == "1 files checked, 1 fixed (address 1, coordinates 1, phone 1, website 1), 0 still flagged"
    assert r["details"]["fixed"] == {"lion": ["address", "coordinates", "phone", "website"]}
    assert result.output.rstrip().endswith("(logged)\n\nAll files look good.")


def test_check_fix_keeps_name_and_skips_unlinked(db, monkeypatch):
    seed(db, "renamed", name="Lion Dance Café (old name)", lat=37.9)
    seed(db, "unlinked", name="Unlinked", place_id=None, lat=37.91, phone=None)
    monkeypatch.setattr(cross_reference, "get_place", lion)
    monkeypatch.setattr(cross_reference, "search_text", lambda q, **kw: [LION])
    result = runner.invoke(cross_reference_md, ["--fix", "renamed", "unlinked"])
    assert result.exit_code == 1, result.output  # the unlinked place is still flagged
    assert "fixed: coordinates" in result.output
    assert "name kept: Lion Dance Café (old name) | Google: Lion Dance Cafe" in result.output
    assert read(db, "renamed")["name"] == "Lion Dance Café (old name)"
    assert read(db, "renamed")["lat"] == round(LION.lat, 7)
    assert read(db, "unlinked")["lat"] == 37.91  # untouched: no place_id
    assert "1 fixed" in result.output and "1 still flagged" in result.output
    assert recent(db)[0]["details"]["flagged"].keys() == {"unlinked"}


def test_check_fix_rejects_clashing_coordinates(db, monkeypatch):
    seed(db, "owner", name="Owner Cafe", place_id="OWNER", phone=None)  # already sits at LION's coordinates
    seed(db, "drifted", lat=37.9)
    before = read(db, "drifted")
    monkeypatch.setattr(cross_reference, "get_place", lion)
    result = runner.invoke(cross_reference_md, ["--fix", "drifted"])
    assert result.exit_code == 1, result.output
    assert "not fixed: coordinates (37.8061, -122.2683) reused by owner and drifted" in result.output
    assert read(db, "drifted") == before


def test_check_no_fix_writes_nothing(db, monkeypatch):
    seed(db, "lion", lat=37.9)
    before = read(db, "lion")
    monkeypatch.setattr(cross_reference, "get_place", lion)
    result = runner.invoke(cross_reference_md, ["lion"])
    assert result.exit_code == 1
    assert read(db, "lion") == before
    assert recent(db) == []


# --- audit ---


def place_with_status(status):
    data = copy.deepcopy(load("details_full.json"))
    data["businessStatus"] = status
    return parse_place(data)


def audit_fixture(db):
    seed(db, "open", name="Lion Dance Cafe", place_id="A", lat=37.80)
    seed(db, "closed", name="Shuttered Vegan Diner", place_id="B", lat=37.81, phone=None)
    seed(db, "temp", name="Temp Cafe", place_id="C", lat=37.82, phone=None)
    seed(db, "weird", name="Weird Cafe", place_id="D", lat=37.83, phone=None)
    seed(db, "broken", name="Broken Cafe", place_id="E", lat=37.84, phone=None)
    seed(db, "noid", name="No Id Cafe", place_id=None, lat=37.85, phone=None)
    responses = {
        "A": place_with_status("OPERATIONAL"),
        "B": parse_place(load("details_closed.json")),
        "C": place_with_status("CLOSED_TEMPORARILY"),
        "D": place_with_status("SOMETHING_NEW"),
    }

    def fake_get(place_id, fields=None):
        fake_get.calls.append(place_id)
        if place_id == "E":
            raise PlacesError("quota")
        return responses[place_id]

    fake_get.calls = []
    return fake_get


def test_audit_groups(db, monkeypatch):
    monkeypatch.setattr(audit, "get_place", audit_fixture(db))
    result = runner.invoke(audit_places, [])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "No previous audit logged." in out
    assert "Permanently closed (1):\n  closed: Shuttered Vegan Diner: CLOSED_PERMANENTLY" in out
    assert "Temporarily closed (1):\n  temp: Temp Cafe: CLOSED_TEMPORARILY" in out
    assert "Unknown status (1):\n  weird: Weird Cafe: SOMETHING_NEW" in out
    assert "Could not check (1):\n  broken: Broken Cafe: quota" in out
    assert not any(line.strip().startswith("open:") for line in out.splitlines())
    assert "5 places audited, 1 without a place_id" in out
    assert out.rstrip().endswith("Logged.")
    r = recent(db)[0]
    assert r["kind"] == "audit" and r["scope"] == "all"
    assert r["summary"] == (
        "5 audited, 1 without place_id; permanently closed: closed; temporarily closed: temp; could not check: broken"
    )
    assert r["details"]["Permanently closed"] == ["closed: Shuttered Vegan Diner: CLOSED_PERMANENTLY"]
    assert read(db, "closed")["closed"] is False  # reported only, not marked


def test_audit_all_operational(db, monkeypatch):
    seed(db, "open", place_id="A")
    monkeypatch.setattr(audit, "get_place", lion)
    result = runner.invoke(audit_places, [])
    assert result.exit_code == 0, result.output
    assert "All 1 audited places are OPERATIONAL." in result.output


def test_audit_accepts_slug_arguments(db, monkeypatch):
    seed(db, "a", place_id="A")
    seed(db, "b", name="B Cafe", place_id="B", lat=37.9, phone=None)
    calls = []

    def fake_get(place_id, fields=None):
        calls.append(place_id)
        return place_with_status("OPERATIONAL")

    monkeypatch.setattr(audit, "get_place", fake_get)
    result = runner.invoke(audit_places, ["a", "--no-log"])
    assert result.exit_code == 0, result.output
    assert calls == ["A"]
    assert "1 places audited" in result.output
    assert "Logged." not in result.output and recent(db) == []
    result = runner.invoke(audit_places, ["zzz"])
    assert result.exit_code == 1 and "unknown slug 'zzz'" in result.output


def test_audit_mark_closed_sets_flag_and_skips_next_time(db, monkeypatch):
    seed(db, "open", place_id="A")
    seed(db, "closed", name="Shuttered Vegan Diner", place_id="B", lat=37.81, phone=None)
    seed(db, "temp", name="Temp Cafe", place_id="C", lat=37.82, phone=None)
    responses = {
        "A": place_with_status("OPERATIONAL"),
        "B": parse_place(load("details_closed.json")),
        "C": place_with_status("CLOSED_TEMPORARILY"),
    }
    calls = []

    def fake_get(place_id, fields=None):
        calls.append(place_id)
        return responses[place_id]

    monkeypatch.setattr(audit, "get_place", fake_get)
    result = runner.invoke(audit_places, ["--mark-closed"])
    assert result.exit_code == 0, result.output
    assert "No previous audit logged." in result.output
    assert "Marked 1 place(s) closed: closed" in result.output
    row = read(db, "closed")
    assert row["closed"] is True and row["body"] == BODY and repo.is_dirty(row)
    assert read(db, "temp")["closed"] is False and read(db, "open")["closed"] is False
    log = recent(db)
    assert len(log) == 1 and log[0]["kind"] == "audit"
    assert log[0]["summary"] == "3 audited, 0 without place_id; permanently closed: closed (marked closed); temporarily closed: temp"
    # a second run skips the closed one without an API call and reports the previous audit
    calls.clear()
    result = runner.invoke(audit_places, ["--no-log"])
    assert "Last audit: " in result.output and "(0 days ago)" in result.output
    assert "2 places audited, 0 without a place_id (cannot be audited), 1 already marked closed" in result.output
    assert "B" not in calls
    assert recent(db) == log


def test_same_street_tolerates_detail_and_abbreviations():
    from scripts.cross_reference import same_street

    assert same_street("800 Bancroft Way Suite #105", "800 Bancroft Way")
    assert same_street("688 San Jose Avenue", "688 San Jose Ave")
    assert same_street("1 Ferry Plaza", "1 Ferry Plz")
    assert not same_street("945 Market St", "455 Market St")
    assert not same_street("1004 Webster St", "2212 Broadway")


def test_check_fix_keeps_unit_detail_and_numberless_addresses(db, monkeypatch):
    seed(db, "detailed", address="380 17th St Suite #4")
    monkeypatch.setattr(cross_reference, "get_place", lion)
    result = runner.invoke(cross_reference_md, ["--fix", "detailed"])
    assert result.exit_code == 0, result.output
    assert read(db, "detailed")["address"] == "380 17th St Suite #4"
    numberless = copy.deepcopy(load("details_full.json"))
    numberless["addressComponents"] = [c for c in numberless["addressComponents"] if "street_number" not in c["types"]]
    monkeypatch.setattr(cross_reference, "get_place", lambda pid, fields=None: parse_place(numberless))
    seed(db, "other", name="Other", address="One Ferry Building", lat=37.9, phone=None, place_id="OTHER")
    result = runner.invoke(cross_reference_md, ["--fix", "other"])
    assert read(db, "other")["address"] == "One Ferry Building"
    assert "Current address" in result.output  # still reported, just not overwritten


# --- pure cores: check_place and audit_rows ---


def recording(place=LION):
    """A get_place stand-in returning `place`; calls recorded as (place_id, fields)."""

    def get(place_id, fields=None):
        get.calls.append((place_id, fields))
        return place

    get.calls = []
    return get


def no_search(*a, **k):
    pytest.fail("search called")


def test_check_place_contact():
    get = recording()
    meta = {**BASE, "phone": "+15105550100"}
    before = dict(meta)
    result = check_place(meta, contact=True, fix=False, get=get, search=no_search)
    assert isinstance(result, CheckResult)
    assert get.calls == [("ChIJfixtureLionDance", CONTACT_FIELDS)]
    assert result.place is LION
    assert result.note is None
    assert result.mismatches == [
        "Current phone number: +15105550100 | Determined phone number: +15105550199"
    ]
    assert result.info == ["Website (not in file): https://example.com/lion-dance"]
    assert result.changed == []
    assert result.meta == before and meta == before


def test_check_place_all_good_core_fields():
    get = recording()
    result = check_place(BASE, contact=False, fix=False, get=get, search=no_search)
    assert get.calls == [("ChIJfixtureLionDance", CORE_FIELDS)]
    assert (result.mismatches, result.info, result.changed) == ([], [], [])


def test_check_place_fix():
    meta = {**BASE, "address": "1 Wrong St", "lat": 37.9, "lon": -122.0, "phone": "+15105550000"}
    before = dict(meta)
    result = check_place(meta, contact=True, fix=True, get=recording(), search=no_search)
    assert result.changed == ["address", "coordinates", "phone", "website"]
    assert "fixed: address, coordinates, phone, website" in result.info
    assert result.mismatches == []
    assert result.meta["address"] == LION.street_address
    assert result.meta["lat"] == round(LION.lat, 7) and result.meta["lon"] == round(LION.lon, 7)
    assert result.meta["phone"] == LION.phone and result.meta["website"] == LION.website
    assert result.meta["name"] == "Lion Dance Cafe"
    assert meta == before  # the caller's dict is never mutated


def test_check_place_fix_nothing_to_fix():
    result = check_place(BASE, contact=True, fix=True, get=recording(), search=no_search)
    assert result.changed == []
    assert result.mismatches == []
    assert not any(line.startswith("fixed") for line in result.info)


def test_check_place_fix_keeps_name():
    meta = {**BASE, "name": "Lion Dance Café (old name)", "lat": 37.9}
    result = check_place(meta, contact=False, fix=True, get=recording(), search=no_search)
    assert result.mismatches == []
    assert result.changed == ["coordinates"]
    assert "name kept: Lion Dance Café (old name) | Google: Lion Dance Cafe" in result.info
    assert result.meta["name"] == "Lion Dance Café (old name)"
    # without fix the name difference is still a mismatch
    result = check_place(meta, contact=False, fix=False, get=recording(), search=no_search)
    assert any(m.startswith("Current name") for m in result.mismatches)
    assert result.changed == []


def test_check_place_search_fallback():
    seen = {}

    def search(query, **kw):
        seen["query"] = query
        seen.update(kw)
        return [SEARCH[0]]

    meta = {**BASE, "place_id": None, "lat": 37.8161}
    result = check_place(meta, contact=False, fix=True, get=recording(), search=search)
    assert seen == {"query": "Lion Dance Cafe 380 17th St", "max_results": 1, "fields": CORE_FIELDS}
    assert result.note == "(no place_id: matched by search to Lion Dance Cafe, ChIJfixtureLionDance)"
    assert result.mismatches == ["Current latitude: 37.8161 | Determined latitude: 37.8061"]
    assert result.changed == []  # never fixes a place without a place_id
    assert result.meta["lat"] == 37.8161

    with pytest.raises(PlacesError, match="no search results"):
        check_place(meta, contact=False, fix=False, get=recording(), search=lambda *a, **k: [])


def test_check_place_missing_name_raises():
    with pytest.raises(ValueError, match="missing name"):
        check_place({**BASE, "name": None}, contact=False, fix=False, get=recording(), search=no_search)
    with pytest.raises(ValueError, match="missing name, address"):
        check_place({}, contact=False, fix=False, get=recording(), search=no_search)


def test_check_place_places_error_propagates():
    def boom(place_id, fields=None):
        raise PlacesError("boom")

    with pytest.raises(PlacesError, match="boom"):
        check_place(BASE, contact=False, fix=False, get=boom, search=no_search)


AUDIT_ROWS = [
    ("open", {**BASE, "name": "Lion Dance Cafe", "place_id": "A"}),
    ("closed", {**BASE, "name": "Shuttered Vegan Diner", "place_id": "B"}),
    ("temp", {**BASE, "name": "Temp Cafe", "place_id": "C"}),
    ("weird", {**BASE, "name": "Weird Cafe", "place_id": "D"}),
    ("broken", {**BASE, "name": "Broken Cafe", "place_id": "E"}),
    ("noid", {**BASE, "name": "No Id Cafe", "place_id": None}),
    ("done", {**BASE, "name": "Done Cafe", "place_id": "F", "closed": True}),
]


def audit_get(delay=0.0):
    responses = {
        "A": place_with_status("OPERATIONAL"),
        "B": parse_place(load("details_closed.json")),
        "C": place_with_status("CLOSED_TEMPORARILY"),
        "D": place_with_status("SOMETHING_NEW"),
    }

    def get(place_id, fields=None):
        get.calls.append(place_id)
        if delay:
            # earlier rows finish later, so the pool has to keep row order itself
            time.sleep(delay * (6 - "ABCDE".index(place_id)))
        if place_id == "E":
            raise PlacesError("quota")
        return responses[place_id]

    get.calls = []
    return get


def test_audit_rows():
    get = audit_get()
    report = audit_rows(AUDIT_ROWS, get=get)
    assert isinstance(report, AuditReport)
    assert report.groups == {
        "Permanently closed": ["closed: Shuttered Vegan Diner: CLOSED_PERMANENTLY"],
        "Temporarily closed": ["temp: Temp Cafe: CLOSED_TEMPORARILY"],
        "Unknown status": ["weird: Weird Cafe: SOMETHING_NEW"],
        "Could not check": ["broken: Broken Cafe: quota"],
    }
    assert report.closed_slugs == ["closed"]
    assert (report.audited, report.no_id, report.already_closed) == (5, 1, 1)
    assert sorted(get.calls) == ["A", "B", "C", "D", "E"]  # nothing fetched for noid / done


def test_audit_rows_empty_and_all_operational():
    report = audit_rows([], get=lambda *a, **k: pytest.fail("get called"))
    assert report == AuditReport()
    assert list(report.groups) == ["Permanently closed", "Temporarily closed", "Unknown status", "Could not check"]
    report = audit_rows([("open", {**BASE, "place_id": "A"})], get=audit_get())
    assert not any(report.groups.values()) and report.audited == 1


def test_audit_rows_workers_equal():
    sequential = audit_rows(AUDIT_ROWS, get=audit_get(), workers=1)
    parallel = audit_rows(AUDIT_ROWS, get=audit_get(delay=0.002), workers=4)
    assert sequential == parallel
    assert parallel.groups["Could not check"] == ["broken: Broken Cafe: quota"]
    # more rows than one bucket, still in row order
    rows = [(f"r{i}", {**BASE, "name": f"Cafe {i}", "place_id": "B"}) for i in range(10)]
    assert audit_rows(rows, get=audit_get(), workers=4).closed_slugs == [f"r{i}" for i in range(10)]
