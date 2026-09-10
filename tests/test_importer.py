"""scripts/importer.py: places/*.md + raw/food -> database rows (photos when scripts.photos exists)."""

import importlib.util
from pathlib import Path

import pytest
from PIL import Image

from scripts import build, repo, runs
from scripts.db import init_db, make_engine
from scripts.importer import import_markdown
from scripts.schema import write_place
from scripts.storage import LocalStorage

HAVE_PHOTOS = importlib.util.find_spec("scripts.photos") is not None

BASE = dict(
    name="Alpha Cafe",
    cuisine="Thai",
    address="1 Main St",
    area="Mission District",
    lat=37.76,
    lon=-122.42,
    phone="+14155550001",
    menu=None,
    drinks=True,
    visited="2024-03-31",
    taste=2,
    value=1,
    instagram_published=False,
)


@pytest.fixture
def layout(tmp_path):
    places = tmp_path / "places"
    raw = tmp_path / "raw" / "food"
    places.mkdir()
    raw.mkdir(parents=True)
    write_place(places / "alpha-cafe.md", BASE, "\nGet the **pad thai**.\n")
    write_place(
        places / "beta-bar.md",
        {**BASE, "name": "Beta Bar", "lat": 37.77, "phone": "+14155550002", "visited": "2025-01-02"},
        "\nGet the **larb**.\n",
    )
    Image.new("RGB", (40, 30), "red").save(raw / "alpha-cafe.jpg")
    Image.new("RGB", (40, 30), "blue").save(raw / "orphan.jpg")
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    return tmp_path, engine, LocalStorage(tmp_path / "media")


def run(layout, **kw):
    root, engine, media = layout
    echoed = []
    with engine.begin() as conn:
        report = import_markdown(
            conn, media, places_dir=root / "places", raw_dir=root / "raw" / "food",
            echo=echoed.append, **kw,
        )
    return report, echoed


def rows(layout):
    with layout[1].connect() as conn:
        return repo.all_rows(conn)


def test_import_rows_and_timestamps(layout):
    report, echoed = run(layout)
    assert report.errors == [] and report.rows == 2
    assert report.orphans == ["orphan"]
    got = {r["slug"]: r for r in rows(layout)}
    assert set(got) == {"alpha-cafe", "beta-bar"}
    # no git history in tmp, so the visited date stands in for the commit date
    for slug, visited in (("alpha-cafe", "2024-03-31"), ("beta-bar", "2025-01-02")):
        r = got[slug]
        assert r["created_at"] == r["updated_at"] == r["published_at"] == f"{visited}T00:00:00Z"
        assert not repo.is_dirty(r)
    assert got["alpha-cafe"]["body"] == "\nGet the **pad thai**.\n"
    with layout[1].connect() as conn:
        r = runs.recent(conn)[0]
    assert r["kind"] == "import" and r["status"] == "ok"
    assert r["details"]["orphans"] == ["orphan"]
    assert "Imported 2 places" in " ".join(echoed)
    assert any("orphan" in line for line in echoed)


def test_photos(layout):
    report, echoed = run(layout)
    got = {r["slug"]: r for r in rows(layout)}
    media = layout[2]
    if HAVE_PHOTOS:
        assert report.photos == 1 and not report.photos_skipped
        assert media.exists("originals/alpha-cafe.jpg")
        for key in ("img/food/alpha-cafe.jpg", "img/food/alpha-cafe.webp", "img/thumb/alpha-cafe.jpg", "img/thumb/alpha-cafe.webp"):
            assert media.exists(key), key
        assert got["alpha-cafe"]["photo_key"] == "originals/alpha-cafe.jpg"
        assert (got["alpha-cafe"]["photo_width"], got["alpha-cafe"]["photo_height"]) == (40, 30)
    else:
        assert report.photos == 0 and report.photos_skipped
        assert any("photos skipped" in line for line in echoed)
        assert media.listing() == {}
        assert got["alpha-cafe"]["photo_key"] is None  # nothing stored, so nothing claimed
        assert got["alpha-cafe"]["photo_width"] is None
    assert got["beta-bar"]["photo_key"] is None


def test_dry_run_writes_nothing(layout):
    report, echoed = run(layout, dry_run=True)
    assert report.errors == [] and report.rows == 2
    assert rows(layout) == []
    assert layout[2].listing() == {}
    assert any(line.startswith("Dry run") for line in echoed)
    with layout[1].connect() as conn:
        assert runs.recent(conn) == []


def test_bad_file_reported_nothing_written(layout):
    (layout[0] / "places" / "broken.md").write_text("---\nname: [x\n---\n")
    report, echoed = run(layout)
    assert report.errors and "broken.md" in report.errors[0]
    assert rows(layout) == []
    assert echoed == report.errors


def test_invalid_place_reported_nothing_written(layout):
    write_place(
        layout[0] / "places" / "no-dish.md",
        {**BASE, "name": "No Dish", "lat": 37.78, "phone": None},
        "\nnothing bold here\n",
    )
    report, _ = run(layout)
    assert any("no-dish: taste: highlight a dish in bold" in e for e in report.errors)
    assert rows(layout) == []


def test_refuses_second_import_without_replace(layout):
    run(layout)
    report, echoed = run(layout)
    assert report.errors == ["database already holds 2 places; use --replace"]
    assert len(rows(layout)) == 2
    Path(layout[0] / "places" / "beta-bar.md").unlink()
    report, _ = run(layout, replace=True)
    assert report.errors == [] and report.rows == 1
    assert [r["slug"] for r in rows(layout)] == ["alpha-cafe"]


def test_duplicate_name_reported(layout):
    write_place(layout[0] / "places" / "alpha-again.md", {**BASE, "lat": 37.79, "phone": None}, "\n**x**\n")
    report, _ = run(layout)
    assert any("name 'Alpha Cafe' reused by" in e for e in report.errors)
    assert rows(layout) == []


def test_git_dates_apply_whatever_the_places_path_looks_like(layout, monkeypatch):
    """git reports repo-relative paths; an absolute --places must still pick them up."""
    monkeypatch.setattr(build, "git_modified_dates", lambda path="places": {"places/alpha-cafe.md": "2026-02-03"})
    report, _ = run(layout)  # run() passes an absolute places_dir
    assert report.errors == []
    got = {r["slug"]: r for r in rows(layout)}
    assert got["alpha-cafe"]["updated_at"] == got["alpha-cafe"]["published_at"] == "2026-02-03T00:00:00Z"
    assert got["beta-bar"]["updated_at"] == "2025-01-02T00:00:00Z"  # not in git: visited
