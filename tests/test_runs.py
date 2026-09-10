from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from scripts import runs
from scripts.db import init_db, make_engine
from scripts.db import runs as runs_table


@pytest.fixture
def conn(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    with engine.begin() as conn:
        yield conn


def test_start_running_finish(conn):
    assert runs.running(conn, "publish") is None
    run_id = runs.start(conn, "publish", scope="test-place", by_email="a@b.c")
    assert isinstance(run_id, int)
    r = runs.running(conn, "publish")
    assert r["id"] == run_id and r["status"] == "running" and r["scope"] == "test-place"
    assert r["by_email"] == "a@b.c" and r["started_at"].endswith("Z") and r["finished_at"] is None
    assert runs.running(conn, "audit") is None
    assert runs.last(conn, "publish") is None
    runs.finish(conn, run_id, "ok", "published 3", details={"pages": 3}, snapshot_key="snap/1.json")
    assert runs.running(conn, "publish") is None
    r = runs.recent(conn)[0]
    assert r["status"] == "ok" and r["summary"] == "published 3" and r["details"] == {"pages": 3}
    assert r["snapshot_key"] == "snap/1.json" and r["error"] is None and r["finished_at"].endswith("Z")
    failed = runs.start(conn, "publish")
    runs.finish(conn, failed, "failed", "boom", error="Traceback")
    assert runs.recent(conn)[0]["error"] == "Traceback"


def test_append_and_last(conn):
    a = runs.append(conn, "check", "0 mismatches", details={"n": 0})
    b = runs.append(conn, "check", "crashed", status="failed", error="x")
    c = runs.append(conn, "audit", "3 closed", by_email="me@x")
    rows = {r["id"]: r for r in runs.recent(conn)}
    assert rows[a]["started_at"] == rows[a]["finished_at"] and rows[a]["status"] == "ok"
    assert rows[b]["status"] == "failed" and rows[c]["by_email"] == "me@x" and rows[c]["scope"] == "all"
    last = runs.last(conn, "check")
    assert last is not None and last.tzinfo is not None
    assert last == datetime.fromisoformat(rows[a]["started_at"])
    assert runs.last(conn, "audit") == datetime.fromisoformat(rows[c]["started_at"])
    assert runs.last(conn, "publish") is None
    with pytest.raises(TypeError):
        runs.append(conn, "check", "x", bogus=1)


def test_recent_order_and_limit(conn):
    ids = [runs.append(conn, "k", f"run {i}") for i in range(5)]
    got = runs.recent(conn, n=3)
    assert [r["id"] for r in got] == ids[::-1][:3]
    assert len(runs.recent(conn)) == 5


def test_running_ignores_stale(conn):
    conn.execute(sa.insert(runs_table).values(
        kind="publish", status="running", started_at=datetime.now(UTC) - timedelta(minutes=30)))
    assert runs.running(conn, "publish") is None
    assert runs.running(conn, "publish", within_minutes=60) is not None
