"""Regression coverage for shared CLI/admin tooling; all network calls are fake."""

from types import SimpleNamespace
from threading import Event

import pytest

from scripts import spatula
from scripts.audit import audit_rows
from scripts.cross_reference import check_place
from scripts.places import PlacesError
from scripts.repo import _to_db


def test_maps_short_link_resolves(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=302, headers={
            "Location": "https://www.google.com/maps/place/Mini+Potstickers/@37,-122"
        }, raise_for_status=lambda: None, close=lambda: None)

    monkeypatch.setattr(spatula.requests, "get", get)
    assert spatula.query_from_maps_url("https://maps.app.goo.gl/example") == "Mini Potstickers"
    assert len(calls) == 1
    assert calls[0][1] == {"timeout": 5, "allow_redirects": False, "stream": True}


@pytest.mark.parametrize("location", ["http://127.0.0.1/", "https://google.com.evil.test/maps/place/X",
                                      "https://user:password@google.com/maps/place/X"])
def test_maps_short_link_rejects_untrusted_redirect(monkeypatch, location):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=302, headers={"Location": location},
                               raise_for_status=lambda: None, close=lambda: None)

    monkeypatch.setattr(spatula.requests, "get", get)
    with pytest.raises(PlacesError, match="outside Google Maps"):
        spatula.query_from_maps_url("https://maps.app.goo.gl/example")
    assert len(calls) == 1


def test_maps_short_link_timeout_is_actionable(monkeypatch):
    def get(*args, **kwargs):
        raise spatula.requests.Timeout()

    monkeypatch.setattr(spatula.requests, "get", get)
    with pytest.raises(PlacesError, match="Search by restaurant name"):
        spatula.query_from_maps_url("https://maps.app.goo.gl/example")


def test_maps_query_url():
    assert spatula.query_from_maps_url("https://www.google.com/maps/search/?api=1&query=Mini+Potstickers") == "Mini Potstickers"
    assert spatula.query_from_maps_url("https://example.com/maps/place/Example") is None


def test_check_validates_before_google():
    def unexpected(*args, **kwargs):
        pytest.fail("invalid review must not call Google")

    with pytest.raises(ValueError, match="Review validation"):
        check_place({"name": "Test", "address": "1 Main St"}, body="", contact=False, fix=False,
                    get=unexpected, search=unexpected)


def test_audit_streams_before_slow_lookup_finishes():
    reported = Event()
    output = []

    def get(pid):
        if pid == "slow":
            assert reported.wait(3), "fast result was not streamed"
        return SimpleNamespace(business_status="CLOSED_PERMANENTLY")

    def on_problem(line):
        output.append(line)
        reported.set()

    report = audit_rows([(p, {"name": p, "place_id": p}) for p in ("slow", "fast")],
                        get=get, on_problem=on_problem)
    assert output[0].startswith("fast:")
    assert report.closed_slugs == ["slow", "fast"]


def test_coordinates_round_on_save():
    assert _to_db({"lat": 37.763333249999, "lon": -122.48010450000001}) == {
        "lat": 37.7633332, "lon": -122.4801045,
    }


def test_intentionally_unlinked_skips_all_google_tools():
    from scripts.enrich import enrich_meta

    def unexpected(*args, **kwargs):
        pytest.fail("intentionally unlinked review must not call Google")

    meta = {"name": "Fiji Airways", "address": "Airplane", "unlinked": True}
    report = audit_rows([("fiji-airways", meta)], get=unexpected)
    assert (report.unlinked, report.no_id, report.audited) == (1, 0, 0)
    assert enrich_meta(meta, search=unexpected, get=unexpected, force=True)[0] == "unchanged"
    result = check_place(meta, contact=False, fix=True, get=unexpected, search=unexpected)
    assert not result.changed and "intentionally unlinked" in result.note


def test_old_database_migration_preserves_rows(tmp_path):
    import json
    from pathlib import Path
    import sqlalchemy as sa
    from scripts import repo
    from scripts.db import init_db, make_engine

    engine = make_engine(f"sqlite:///{tmp_path}/old.db")
    init_db(engine)
    rows = json.loads((Path(__file__).parent / "fixtures/snapshot.json").read_text())
    with engine.begin() as conn:
        repo.from_snapshot_rows(conn, rows)
        before = repo.all_rows(conn)
        conn.execute(sa.text("ALTER TABLE places DROP COLUMN unlinked"))
    init_db(engine)
    init_db(engine)
    with engine.begin() as conn:
        assert repo.all_rows(conn) == before
        repo.update(conn, "bare-place", {"unlinked": True}, touch=False)
        saved = repo.all_rows(conn)
        repo.from_snapshot_rows(conn, saved, replace=True)
        assert repo.all_rows(conn) == saved
