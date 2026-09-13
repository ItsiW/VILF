"""`./vilf` commands end to end against a tmp SQLite, media and site directory."""

import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa
from click.testing import CliRunner

from scripts import repo, runs
from scripts.cli import cli
from scripts.config import settings
from scripts.db import make_engine
from scripts.snapshot import load_rows
from scripts.storage import LocalStorage

REPO_ROOT = Path(__file__).resolve().parent.parent
HAVE_PHOTOS = importlib.util.find_spec("scripts.photos") is not None
runner = CliRunner()

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
def env(tmp_path, monkeypatch):
    """A site root (html/static/about) with settings pointing into tmp."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "html").symlink_to(REPO_ROOT / "html")
    (root / "about.md").symlink_to(REPO_ROOT / "about.md")
    (root / "static").mkdir()
    for file in (REPO_ROOT / "static").iterdir():
        if file.is_file():
            shutil.copy(file, root / "static" / file.name)
    monkeypatch.chdir(root)
    url = f"sqlite:///{tmp_path}/cli.db"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("VILF_MEDIA_STORAGE", str(tmp_path / "media"))
    monkeypatch.setenv("VILF_SITE_STORAGE", str(tmp_path / "site"))
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("VILF_URL_MAP", raising=False)
    settings.cache_clear()
    yield {"root": root, "tmp": tmp_path, "engine": make_engine(url), "media": LocalStorage(tmp_path / "media"),
           "site": LocalStorage(tmp_path / "site")}
    settings.cache_clear()


def invoke(*args, **kw):
    return runner.invoke(cli, list(args), catch_exceptions=False, **kw)


def rows(env):
    with env["engine"].connect() as conn:
        return repo.all_rows(conn)


def imported(env):
    result = invoke("db", "init")
    assert result.exit_code == 0, result.output
    with env["engine"].begin() as conn:
        for slug, meta, body in [
            ("alpha-cafe", BASE, "Get the **pad thai**."),
            ("beta-bar", {**BASE, "name": "Beta Bar", "lat": 37.77, "phone": None, "visited": "2025-01-02"}, "Get the **larb**."),
        ]:
            repo.insert(conn, repo.meta_to_row(meta, body, slug=slug))
    return result


def test_uninitialised_database_is_a_clear_error(env):
    db_file = env["tmp"] / "cli.db"
    for args in (("build", "--out", str(env["tmp"] / "out")), ("db", "snapshot"), ("publish",)):
        result = invoke(*args)
        assert result.exit_code == 1, result.output
        assert "database not initialised" in result.output and "./vilf db init" in result.output
    assert not db_file.exists()  # the check runs before an empty SQLite file is created
    # tables missing in an existing database file (e.g. a sqlite file made by something else)
    sa.create_engine(f"sqlite:///{db_file}").connect().close()
    result = invoke("db", "snapshot")
    assert result.exit_code == 1 and "database not initialised" in result.output
    # restore-snapshot initialises the database themselves
    result = invoke("db", "restore-snapshot", str(REPO_ROOT / "tests" / "fixtures" / "snapshot.json"))
    assert result.exit_code == 0, result.output
    assert len(rows(env)) == 6


def test_db_init_creates_tables(env):
    result = invoke("db", "init")
    assert result.exit_code == 0 and "Initialised sqlite:///" in result.output
    assert set(sa.inspect(env["engine"]).get_table_names()) >= {"places", "runs"}
    assert invoke("db", "init").exit_code == 0  # idempotent


def test_snapshot_and_restore_round_trip(env):
    imported(env)
    before = rows(env)
    path = env["tmp"] / "snap.json"
    result = invoke("db", "snapshot", str(path))
    assert result.exit_code == 0, result.output
    assert load_rows(path.read_text()) == before
    result = invoke("db", "snapshot")
    assert load_rows(result.output) == before
    # a local file
    with env["engine"].begin() as conn:
        repo.update(conn, "alpha-cafe", {"taste": 3})
    result = invoke("db", "restore-snapshot", str(path))
    assert result.exit_code == 0 and "Restored 2 places" in result.output
    assert rows(env) == before
    # a media storage key
    env["media"].put("snapshots/x.json", json.dumps(before[:1]).encode(), content_type="application/json")
    result = invoke("db", "restore-snapshot", "snapshots/x.json")
    assert result.exit_code == 0, result.output
    assert rows(env) == before[:1]
    with env["engine"].connect() as conn:
        r = runs.recent(conn)[0]
    assert r["kind"] == "restore" and r["snapshot_key"] == "snapshots/x.json"


def test_build_source_db(env):
    imported(env)
    (env["tmp"] / "media" / "img" / "food").mkdir(parents=True, exist_ok=True)
    (env["tmp"] / "media" / "img" / "food" / "x.jpg").write_bytes(b"jpg")
    out = env["tmp"] / "out"
    result = invoke("build", "--out", str(out))
    assert result.exit_code == 0, result.output
    assert "Done building VILF with 2 places" in result.output
    assert (out / "places" / "alpha-cafe" / "index.html").is_file()
    assert (out / "img" / "food" / "x.jpg").read_bytes() == b"jpg"  # local media copied by default
    assert "<title>Alpha Cafe" in (out / "places" / "alpha-cafe" / "index.html").read_text()


def test_build_snapshot_flag_infers_source(env):
    snap = REPO_ROOT / "tests" / "fixtures" / "snapshot.json"
    out = env["tmp"] / "out"
    result = invoke("build", "--snapshot", str(snap), "--out", str(out))
    assert result.exit_code == 0, result.output
    assert "5 open, 1 closed" in result.output
    assert (out / "places" / "gone-place" / "index.html").is_file()
    result = invoke("build", "--source", "snapshot", "--out", str(out))
    assert result.exit_code == 2 and "--snapshot" in result.output


def test_legacy_commands_are_removed(env):
    assert invoke("build", "--source", "files").exit_code == 2
    assert invoke("db", "import-markdown").exit_code == 2


def test_publish_end_to_end(env):
    imported(env)
    with env["engine"].begin() as conn:
        repo.update(conn, "alpha-cafe", {"taste": 3})
    result = invoke("publish")
    assert result.exit_code == 0, result.output
    assert result.output.startswith("ok: ")
    assert "cdn: skipped" in result.output and "changes: +2 -0 ~0" in result.output
    assert env["site"].exists("places/alpha-cafe/index.html")
    assert len([k for k in env["media"].listing() if k.startswith("snapshots/")]) == 1
    assert not any(repo.is_dirty(r) for r in rows(env))
    result = invoke("publish")
    assert result.exit_code == 0 and "0 uploaded, 0 deleted" in result.output


def test_publish_failed_exit_1(env):
    imported(env)
    with env["engine"].begin() as conn:
        repo.update(conn, "alpha-cafe", {"body": "\nno dish in bold\n"})
    result = invoke("publish")
    assert result.exit_code == 1
    assert result.output.startswith("failed: ")
    assert "alpha-cafe: taste: highlight a dish in bold" in result.output
    assert env["site"].listing() == {}


def test_publish_running_is_a_click_error(env):
    imported(env)
    with env["engine"].begin() as conn:
        runs.start(conn, "publish")
    result = invoke("publish")
    assert result.exit_code == 1 and "still running" in result.output


def test_serve_uses_uvicorn(env, monkeypatch):
    calls = []
    fake = types.ModuleType("uvicorn")
    fake.run = lambda app, **kw: calls.append((app, kw))
    monkeypatch.setitem(sys.modules, "uvicorn", fake)
    monkeypatch.setenv("PORT", "8123")
    settings.cache_clear()
    result = invoke("serve", "--reload")
    assert result.exit_code == 0, result.output
    assert calls == [("app.main:app", {"host": "0.0.0.0", "port": 8123, "reload": True})]
