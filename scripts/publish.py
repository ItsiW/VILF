"""Publish: render the database to a temp dir and sync it into site storage.

One publish = validate every row, write a snapshot of the rows to media
storage, render the site, upload the files whose md5 differs from what site
storage already holds, delete stale objects (with a mass-delete guard),
invalidate the CDN, mark the rows published and log a `runs` row.

Keys under img/ in site storage are never touched: the load balancer routes
/img/* to the media bucket, and the local static/img cache must not be pushed.

Ordering note: uploads and the CDN invalidation happen before mark_published
and runs.finish. If something raises after the uploads the site is already
updated while the rows stay dirty; the next publish reconciles (0 uploads,
rows marked published).

The `running` row is committed on its own connection before any work starts
so that a second process (another `./vilf publish`, or the app) sees it; the
caller's transaction, which may be open for the whole run, only holds the
finish. That needs the caller's connection to have no uncommitted writes when
publish() is called (SQLite allows one writer at a time).
"""

import hashlib
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy import Connection

from . import indexnow, render, repo, runs, schema, snapshot
from .config import Settings
from .db import runs as runs_table
from .snapshot import Diff, diff_rows
from .storage import Storage, guess_content_type

MASS_DELETE_MIN = 25
MASS_DELETE_RATIO = 0.2
SHORT_CACHE = "public, max-age=3600"
LONG_CACHE = "public, max-age=86400"
SHORT_CACHE_SUFFIXES = frozenset({".html", ".json", ".geojson", ".txt", ".xml", ".md"})
UNMANAGED_PREFIX = "img/"
UPLOAD_WORKERS = 16

_LOCK = threading.Lock()


class PublishRunning(RuntimeError):
    """Another publish is in progress (this process or a recent `running` runs row)."""


class CdnInvalidator(Protocol):
    def invalidate(self, paths: list[str]) -> None: ...


class GcpCdnInvalidator:
    """Cloud CDN cache invalidation through the compute API; does not wait for the operation."""

    def __init__(self, project: str, url_map: str):
        self.project = project
        self.url_map = url_map
        self._client = None

    def invalidate(self, paths: list[str]) -> None:
        from google.cloud import compute_v1

        if self._client is None:
            self._client = compute_v1.UrlMapsClient()
        for path in paths:
            self._client.invalidate_cache(
                project=self.project,
                url_map=self.url_map,
                cache_invalidation_rule_resource={"path": path},
            )


@dataclass
class PublishResult:
    run_id: int
    status: str  # 'ok' | 'failed'
    uploaded: int
    deleted: int
    unchanged: int
    snapshot_key: str | None
    changes: Diff | None
    error: str | None
    cdn_invalidated: bool
    seconds: float
    partially_applied: bool = False


def validate_rows(rows: list[dict]) -> list[str]:
    """validate_place per row ('<slug>: <problem>') and, when all pass, validate_unique."""
    problems = []
    for row in rows:
        meta = {k: v for k, v in row.items() if k not in render.SNAPSHOT_ONLY_KEYS}
        problems += [f"{row['slug']}: {p}" for p in schema.validate_place(meta, row["body"], row["slug"])]
    if problems:
        return problems
    entries = [
        {
            "slug": row["slug"],
            "name": row["name"],
            "menu": row["menu"],
            "phone": row["phone"],
            "lat": row["lat"],
            "lon": row["lon"],
            "blurb": render.format_blurb(row["body"]),
        }
        for row in rows
    ]
    return schema.validate_unique(entries)


def _cache_control(key: str) -> str:
    return SHORT_CACHE if Path(key).suffix.lower() in SHORT_CACHE_SUFFIXES else LONG_CACHE


def _walk(out_dir: Path) -> dict[str, tuple[Path, str, str]]:
    """{key: (path, md5hex, content type)} for every file under out_dir, img/ excluded."""
    desired = {}
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        key = path.relative_to(out_dir).as_posix()
        if key.startswith(UNMANAGED_PREFIX):
            continue
        desired[key] = (path, hashlib.md5(path.read_bytes()).hexdigest(), guess_content_type(key))
    return desired


def _snapshot_key(now: datetime) -> str:
    return f"snapshots/{now:%Y%m%dT%H%M%S.%f}Z.json"


def _last_snapshot_key(conn: Connection) -> str | None:
    return conn.execute(
        sa.select(runs_table.c.snapshot_key)
        .where(
            runs_table.c.kind == "publish",
            runs_table.c.status == "ok",
            runs_table.c.snapshot_key.is_not(None),
        )
        .order_by(runs_table.c.started_at.desc(), runs_table.c.id.desc())
        .limit(1)
    ).scalar()


def last_snapshot_rows(conn: Connection, media: Storage) -> list[dict]:
    """Rows of the latest ok publish's snapshot; [] when there is none (or it is gone)."""
    key = _last_snapshot_key(conn)
    if not key or not media.exists(key):
        return []
    return snapshot.load_rows(media.get(key).decode("utf-8"))


def pending_diff(conn: Connection, media: Storage) -> Diff:
    return diff_rows(last_snapshot_rows(conn, media), repo.all_rows(conn))


def _upload_all(site: Storage, to_upload: dict[str, tuple[Path, str, str]]) -> tuple[int, str | None]:
    """Upload in parallel; on the first failure cancel the rest. Returns (done, error)."""
    done = 0
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        futures = {
            pool.submit(
                site.put, key, path.read_bytes(), content_type=ctype, cache_control=_cache_control(key)
            ): key
            for key, (path, _, ctype) in to_upload.items()
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:  # noqa: BLE001 - any storage failure fails the publish
                for other in futures:
                    other.cancel()
                pool.shutdown(wait=True, cancel_futures=True)
                return done, f"upload of {futures[future]} failed: {e}"
            done += 1
    return done, None


def _delete_all(site: Storage, keys: list[str]) -> tuple[int, str | None]:
    done = 0
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        futures = {pool.submit(site.delete, key): key for key in keys}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:  # noqa: BLE001
                for other in futures:
                    other.cancel()
                pool.shutdown(wait=True, cancel_futures=True)
                return done, f"delete of {futures[future]} failed: {e}"
            done += 1
    return done, None


def publish(
    conn: Connection,
    *,
    media: Storage,
    site: Storage,
    settings: Settings,
    cdn: CdnInvalidator | None = None,
    by_email: str | None = None,
    force: bool = False,
    today: date | None = None,
    html_dir="html",
    static_dir="static",
    about_path="about.md",
) -> PublishResult:
    """Publish the database to site storage.

    Raises PublishRunning when another publish is in flight. Any other exception
    becomes a failed result (error = the traceback) so the run row is finished
    and committed by the caller instead of lingering as `running`.
    """
    if not _LOCK.acquire(blocking=False):
        raise PublishRunning("another publish is running in this process")
    try:
        active = runs.running(conn, "publish")
        if active:
            raise PublishRunning(
                f"publish run {active['id']} started {active['started_at']} is still running"
            )
        started = time.monotonic()
        with conn.engine.begin() as own:  # committed now, visible to other processes
            run_id = runs.start(own, "publish", by_email=by_email)
        progress = {"uploaded": 0, "deleted": 0, "unchanged": 0, "partially_applied": False}
        try:
            return _publish(
                conn, run_id, started, media=media, site=site, settings=settings, cdn=cdn,
                force=force, today=today, html_dir=html_dir, static_dir=static_dir,
                about_path=about_path, progress=progress,
            )
        except Exception:  # noqa: BLE001 - reported, not raised, so the row is not left running
            error = traceback.format_exc()
            conn.rollback()
            # The caller may own an engine.begin() context, which cannot be reused
            # after rollback. Record failure independently, including SQL failures.
            with conn.engine.begin() as own:
                runs.finish(own, run_id, "failed", "crashed: " + error.strip().splitlines()[-1], error=error,
                            details=progress, snapshot_key=progress.get("snapshot_key"))
            return PublishResult(
                run_id, "failed", progress["uploaded"], progress["deleted"], progress["unchanged"],
                progress.get("snapshot_key"), None, error, progress.get("cdn_invalidated", False),
                time.monotonic() - started, progress["partially_applied"],
            )
    finally:
        _LOCK.release()


def _publish(conn, run_id, started, *, media, site, settings, cdn, force, today,
             html_dir, static_dir, about_path, progress) -> PublishResult:
    from .storage import storage_from_url

    if settings.backup_storage:
        if settings.backup_storage in (settings.media_storage, settings.site_storage):
            raise ValueError("backup storage must be separate from public media and site storage")
        snapshots = storage_from_url(settings.backup_storage)
        if settings.backup_storage.startswith("gs://"):
            snapshots.bucket.reload()
            if snapshots.bucket.iam_configuration.public_access_prevention != "enforced":
                raise ValueError("backup bucket must enforce public access prevention")
    elif settings.media_storage.startswith("gs://"):
        raise ValueError("VILF_BACKUP_STORAGE is required for cloud publishing")
    else:
        snapshots = media  # Existing local workflows and fixtures.
    snapshot_key = None
    counts = progress
    cdn_invalidated = False

    def fail(error: str, summary: str | None = None) -> PublishResult:
        runs.finish(
            conn, run_id, "failed", summary or error.splitlines()[0], error=error,
            snapshot_key=snapshot_key, details={**counts, "cdn_invalidated": cdn_invalidated},
        )
        return PublishResult(
            run_id, "failed", counts["uploaded"], counts["deleted"], counts["unchanged"],
            snapshot_key, None, error, cdn_invalidated, time.monotonic() - started,
            counts["partially_applied"],
        )

    # (b) rows and validation: nothing is written when a row is broken
    rows = repo.all_rows(conn)
    problems = validate_rows(rows)
    if problems:
        return fail("\n".join(problems), f"{len(problems)} validation problem(s)")
    previous = last_snapshot_rows(conn, snapshots)

    # (c) snapshot
    now = datetime.now(UTC)
    snapshot_key = _snapshot_key(now)
    progress["snapshot_key"] = snapshot_key
    snapshots.put(snapshot_key, snapshot.dump_rows(rows).encode("utf-8"), content_type="application/json")

    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "site"
        # (d) render
        try:
            render.render_site(
                rows, out_dir, site_url=settings.site_url, html_dir=html_dir,
                static_dir=static_dir, about_path=about_path, today=today,
            )
        except render.RenderError as e:
            return fail("\n".join(e.problems), f"{len(e.problems)} render problem(s)")

        # (e) what is there vs what should be
        desired = _walk(out_dir)
        existing = {k: v for k, v in site.listing().items() if not k.startswith(UNMANAGED_PREFIX)}
        to_upload = {k: v for k, v in desired.items() if existing.get(k) != v[1]}
        counts["unchanged"] = len(desired) - len(to_upload)

        # Check the deletion guard before changing any public files.
        stale = sorted(set(existing) - set(desired))
        limit = max(MASS_DELETE_MIN, MASS_DELETE_RATIO * len(existing))
        if stale and len(stale) > limit and not force:
            return fail(f"refusing to delete {len(stale)} of {len(existing)} objects (use force)")

        # (f) uploads; a failure stops before any delete
        counts["partially_applied"] = bool(to_upload or stale)
        done, error = _upload_all(site, to_upload)
        counts["uploaded"] = done
        if error:
            return fail(error)

        # (g) stale objects, guarded against wiping the site
        counts["deleted"], error = _delete_all(site, stale)
        if error:
            return fail(error)

        # (h) CDN
        cdn_error = None
        if cdn is not None:
            try:
                cdn.invalidate(["/*"])
                cdn_invalidated = True
                progress["cdn_invalidated"] = True
            except Exception as e:  # noqa: BLE001 - stale cache is not a failed publish
                cdn_error = str(e)

        # (i) bookkeeping
        repo.mark_published(conn, [r["slug"] for r in rows if repo.is_dirty(r)], now)
        changes = diff_rows(previous, rows)
        summary = f"{counts['uploaded']} uploaded, {counts['deleted']} deleted, {counts['unchanged']} unchanged"
        details = {
            **counts,
            "partially_applied": False,
            "changes": {"added": changes.added, "removed": changes.removed, "changed": changes.changed},
            "cdn_invalidated": cdn_invalidated,
            "cdn_error": cdn_error,
        }

        # (j) IndexNow, non-fatal
        if settings.indexnow:
            details["indexnow"] = _submit_indexnow(out_dir, static_dir, settings, today)

    runs.finish(conn, run_id, "ok", summary, details=details, snapshot_key=snapshot_key)
    return PublishResult(
        run_id, "ok", counts["uploaded"], counts["deleted"], counts["unchanged"],
        snapshot_key, changes, None, cdn_invalidated, time.monotonic() - started,
    )


def _submit_indexnow(out_dir: Path, static_dir, settings: Settings, today) -> str:
    key = indexnow.find_key(static_dir)
    if not key:
        return "no key file"
    urls = indexnow.fresh_urls(out_dir / "sitemap.xml", today=today)
    if not urls:
        return "nothing fresh"
    try:
        response = indexnow.submit(urls, key=key, host=urlparse(settings.site_url).netloc)
    except Exception as e:  # noqa: BLE001
        return f"failed: {e}"
    return f"submitted {len(urls)} URL(s), HTTP {response.status_code}"
