import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import repo, schema
from scripts.db import init_db, make_engine

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "snapshot.json").read_text())
SORTED = sorted((dict(r, unlinked=False) for r in FIXTURE), key=lambda r: r["slug"])


def by_slug(slug):
    return next(dict(r) for r in FIXTURE if r["slug"] == slug)


@pytest.fixture
def conn(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    with engine.begin() as conn:
        repo.from_snapshot_rows(conn, FIXTURE)
        yield conn


def test_round_trip_matches_fixture(conn):
    assert repo.all_rows(conn) == SORTED


def test_null_timestamps_are_filled(conn):
    row = by_slug("test-place")
    row.update(slug="new-place", name="New Place", lat=1.0, lon=1.0, phone=None, menu=None,
               place_id=None, created_at=None, updated_at=None, published_at=None)
    repo.from_snapshot_rows(conn, [row])
    got = repo.get(conn, "new-place")
    assert got["created_at"].endswith("Z") and got["updated_at"] == got["created_at"]
    assert datetime.fromisoformat(got["created_at"]).tzinfo is not None


def test_non_utc_timestamps_are_normalised(conn):
    row = by_slug("test-place")
    row.update(slug="tz-place", name="TZ Place", lat=1.0, lon=1.0, phone=None, menu=None,
               place_id=None, updated_at="2026-01-01T14:00:00+02:00", published_at="2026-01-01T12:30:00Z")
    repo.from_snapshot_rows(conn, [row])
    got = repo.get(conn, "tz-place")
    assert got["updated_at"] == "2026-01-01T12:00:00Z"
    assert not repo.is_dirty(got)


def test_row_to_meta_matches_load_place(conn, tmp_path):
    for row in FIXTURE:
        meta, body = repo.row_to_meta(row)
        assert list(meta) == schema.KNOWN_KEYS
        assert schema.validate_place(meta, body, row["slug"]) == []
        path = tmp_path / f"{row['slug']}.md"
        schema.write_place(path, meta, body)
        assert schema.load_place(path) == (meta, body)


def test_meta_to_row_inverse(conn):
    for row in FIXTURE:
        meta, body = repo.row_to_meta(row)
        extra = {k: row[k] for k in ["slug", "photo_key", "photo_width", "photo_height", "photo_crop_y"]}
        rebuilt = repo.meta_to_row(meta, body, **extra)
        expect = dict(row, unlinked=False, created_at=None, updated_at=None, published_at=None)
        assert rebuilt == expect


def test_get_missing(conn):
    assert repo.get(conn, "nope") is None


def test_unique_slug(conn):
    assert repo.unique_slug(conn, "new") == "new"
    assert repo.unique_slug(conn, "test-place") == "test-place-0"
    row = by_slug("test-place")
    row.update(slug="test-place-0", name="Copy", lat=0.0, lon=0.0, phone=None, menu=None, place_id=None)
    repo.insert(conn, row)
    assert repo.unique_slug(conn, "test-place") == "test-place-1"
    # spatula quirk, kept on purpose: a trailing -N is replaced, not extended
    row.update(slug="route-66", name="Route", lat=0.5, lon=0.5)
    repo.insert(conn, row)
    assert repo.unique_slug(conn, "route-66") == "route-0"


def test_validate_for_save(conn):
    new = by_slug("draft-place")
    new.update(slug="another", name="Another", place_id=None, lat=0.0, lon=0.0,
               body="\nFresh **stuff** here.\n")
    assert repo.validate_for_save(conn, new) == []
    dup_name = dict(new, name="Test Place")
    assert any("name 'Test Place' reused" in p for p in repo.validate_for_save(conn, dup_name))
    dup_blurb = dict(new, body=by_slug("test-place")["body"])
    assert any(p.startswith("blurb ") for p in repo.validate_for_save(conn, dup_blurb))
    edited = by_slug("test-place")
    edited["body"] = "\nNow the **green papaya salad** is the star.\n"
    assert repo.validate_for_save(conn, edited) == []
    assert repo.validate_for_save(conn, by_slug("test-place")) == []
    no_bold = dict(new, body="\nNothing bold.\n")
    assert any("highlight a dish" in p for p in repo.validate_for_save(conn, no_bold))


def test_validate_for_save_rename(conn):
    renamed = dict(by_slug("test-place"), slug="test-place-renamed")
    # Without old_slug the stored row collides with its own new version.
    assert len(repo.validate_for_save(conn, renamed)) == 5
    assert repo.validate_for_save(conn, renamed, old_slug="test-place") == []
    # Other places are still checked against the renamed row.
    clash = dict(renamed, name="Draft Place")
    problems = repo.validate_for_save(conn, clash, old_slug="test-place")
    assert any("name 'Draft Place' reused" in p for p in problems)
    assert repo.update(conn, "test-place", {"slug": "test-place-renamed"})["slug"] == "test-place-renamed"


def test_search(conn):
    slugs = lambda rows: {r["slug"] for r in rows}
    assert slugs(repo.search(conn, "thai")) == {"test-place", "brackets-cafe"}
    assert slugs(repo.search(conn, "BRACK")) == {"brackets-cafe"}
    assert slugs(repo.search(conn, "shattuck")) == {"phone-only"}
    assert slugs(repo.search(conn, "oakland")) == {"gone-place", "draft-place"}
    assert slugs(repo.search(conn, filter="dirty")) == {"bare-place", "draft-place"}
    assert slugs(repo.search(conn, filter="closed")) == {"gone-place"}
    assert slugs(repo.search(conn, filter="nophoto")) == {"bare-place", "draft-place"}
    assert slugs(repo.search(conn, "mexican", filter="dirty")) == {"bare-place"}
    assert len(repo.search(conn)) == len(FIXTURE)
    with pytest.raises(ValueError):
        repo.search(conn, filter="bogus")


def test_dirty_lifecycle(conn):
    assert not repo.is_dirty(by_slug("test-place"))
    assert repo.is_dirty(by_slug("bare-place"))
    assert {r["slug"] for r in repo.dirty_rows(conn)} == {"bare-place", "draft-place"}
    untouched = repo.update(conn, "test-place", {"value": 2}, touch=False)
    assert untouched["value"] == 2 and not repo.is_dirty(untouched)
    touched = repo.update(conn, "test-place", {"value": 3})
    assert repo.is_dirty(touched)
    now = datetime.now(UTC) + timedelta(seconds=1)
    repo.mark_published(conn, ["test-place", "bare-place"], now)
    assert {r["slug"] for r in repo.dirty_rows(conn)} == {"draft-place"}
    assert repo.get(conn, "bare-place")["published_at"] == now.isoformat().replace("+00:00", "Z")
    repo.mark_published(conn, [], now)  # no-op
    repo.mark_published(conn, ["draft-place"], now.isoformat().replace("+00:00", "Z"))
    assert repo.dirty_rows(conn) == []


def test_insert_and_update(conn):
    row = by_slug("draft-place")
    row.update(slug="inserted", name="Inserted", lat=0.0, lon=0.0, place_id=None,
               phone="", created_at="2000-01-01T00:00:00Z", published_at="2000-01-01T00:00:00Z")
    stored = repo.insert(conn, row)
    assert stored["published_at"] is None and stored["phone"] is None
    assert stored["created_at"].startswith("2026") or stored["created_at"] > "2000"
    assert stored["created_at"] == stored["updated_at"]
    assert repo.is_dirty(stored)
    # a second row with phone '' must not trip UNIQUE(phone)
    repo.insert(conn, dict(row, slug="inserted-2", name="Inserted 2", lat=0.1, lon=0.1))
    renamed = repo.update(conn, "inserted", {"slug": "renamed", "closed": True})
    assert renamed["slug"] == "renamed" and renamed["closed"] is True
    assert repo.get(conn, "inserted") is None
    with pytest.raises(KeyError):
        repo.update(conn, "inserted", {"closed": False})


def test_delete(conn):
    with pytest.raises(ValueError):
        repo.delete(conn, "test-place")
    repo.delete(conn, "draft-place")
    assert repo.get(conn, "draft-place") is None
    with pytest.raises(KeyError):
        repo.delete(conn, "draft-place")


def test_distinct_values(conn):
    assert repo.distinct_values(conn, "cuisine") == ["Ethiopian", "Mexican", "Thai"]
    assert repo.distinct_values(conn, "area") == ["Berkeley", "Downtown Oakland", "Mission District"]
    assert repo.distinct_values(conn, "menu") == ["https://example.com/menu"]


def test_from_snapshot_rows_replace(conn):
    repo.from_snapshot_rows(conn, [by_slug("gone-place")], replace=True)
    assert [r["slug"] for r in repo.all_rows(conn)] == ["gone-place"]
