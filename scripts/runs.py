"""Run log over the `runs` table: publish/check/audit/... runs and their outcomes."""

from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import Connection

from .db import runs
from .repo import _iso, _now, _parse_dt

_EXTRA = ("scope", "by_email", "details", "snapshot_key", "error")


def _row(m) -> dict:
    d = dict(m)
    d["started_at"] = _iso(d["started_at"])
    d["finished_at"] = _iso(d["finished_at"])
    return d


def start(conn: Connection, kind: str, scope: str = "all", by_email: str | None = None) -> int:
    return conn.execute(
        sa.insert(runs)
        .values(kind=kind, scope=scope, by_email=by_email, started_at=_now(), status="running")
        .returning(runs.c.id)
    ).scalar_one()


def finish(
    conn: Connection,
    run_id: int,
    status: str,
    summary: str,
    *,
    details=None,
    snapshot_key: str | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        sa.update(runs)
        .where(runs.c.id == run_id)
        .values(
            finished_at=_now(), status=status, summary=summary,
            details=details, snapshot_key=snapshot_key, error=error,
        )
    )


def append(conn: Connection, kind: str, summary: str, **kw) -> int:
    """Log an already-finished run in one go (status defaults to 'ok')."""
    status = kw.pop("status", "ok")
    unknown = set(kw) - set(_EXTRA)
    if unknown:
        raise TypeError(f"unexpected fields {sorted(unknown)}")
    now = _now()
    return conn.execute(
        sa.insert(runs)
        .values(kind=kind, summary=summary, status=status, started_at=now, finished_at=now, **kw)
        .returning(runs.c.id)
    ).scalar_one()


def last(conn: Connection, kind: str) -> datetime | None:
    """started_at (aware UTC) of the latest run of `kind` that finished ok."""
    m = conn.execute(
        sa.select(runs.c.started_at)
        .where(runs.c.kind == kind, runs.c.status == "ok")
        .order_by(runs.c.started_at.desc(), runs.c.id.desc())
        .limit(1)
    ).scalar()
    return _parse_dt(m)


def recent(conn: Connection, n: int = 20) -> list[dict]:
    q = sa.select(runs).order_by(runs.c.started_at.desc(), runs.c.id.desc()).limit(n)
    return [_row(m) for m in conn.execute(q).mappings()]


def running(conn: Connection, kind: str, within_minutes: int = 15) -> dict | None:
    """The newest still-running run of `kind` started recently; older ones count as crashed."""
    cutoff = _now() - timedelta(minutes=within_minutes)
    m = conn.execute(
        sa.select(runs)
        .where(runs.c.kind == kind, runs.c.status == "running", runs.c.started_at >= cutoff)
        .order_by(runs.c.started_at.desc(), runs.c.id.desc())
        .limit(1)
    ).mappings().first()
    return None if m is None else _row(m)
