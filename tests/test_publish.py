"""scripts/publish.py against LocalStorage, a tmp SQLite and a recording fake CDN."""

import json
from datetime import date
from pathlib import Path

import pytest
import requests

from scripts import publish as publish_mod
from scripts import repo, runs
from scripts.config import Settings
from scripts.db import init_db, make_engine
from scripts.publish import (
    MASS_DELETE_MIN,
    PublishRunning,
    last_snapshot_rows,
    pending_diff,
    publish,
)
from scripts.snapshot import diff_rows
from scripts.storage import LocalStorage

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "snapshot.json"
TODAY = date(2026, 9, 9)
FIXTURE = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
SLUGS = sorted(r["slug"] for r in FIXTURE)


class FakeCdn:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def invalidate(self, paths):
        if self.fail:
            raise RuntimeError("cdn down")
        self.calls.append(list(paths))


class RecordingStorage(LocalStorage):
    """LocalStorage that records puts and can fail on one key."""

    def __init__(self, root, fail_on=None):
        super().__init__(root)
        self.puts = []
        self.fail_on = fail_on

    def put(self, key, data, *, content_type, cache_control=None):
        if key == self.fail_on:
            raise RuntimeError("bucket exploded")
        self.puts.append((key, content_type, cache_control))
        super().put(key, data, content_type=content_type, cache_control=cache_control)


@pytest.fixture
def env(tmp_path, make_site_root):
    (tmp_path / "root").mkdir()
    root = make_site_root(tmp_path / "root")
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    with engine.begin() as conn:
        repo.from_snapshot_rows(conn, FIXTURE)
    # commit-as-you-go, like the CLI's transaction: run() commits a test's edits before publishing
    with engine.connect() as conn:
        yield {
            "conn": conn,
            "engine": engine,
            "root": root,
            "media": LocalStorage(tmp_path / "media"),
            "site": RecordingStorage(tmp_path / "site"),
            "cdn": FakeCdn(),
        }


def run(env, **kw):
    kw.setdefault("media", env["media"])
    kw.setdefault("site", env["site"])
    kw.setdefault("cdn", env["cdn"])
    kw.setdefault("settings", Settings())
    kw.setdefault("today", TODAY)
    root = env["root"]
    env["conn"].commit()
    return publish(
        env["conn"], html_dir=root / "html", static_dir=root / "static", about_path=root / "about.md", **kw
    )


def test_snapshots_use_separate_backup_storage(env, tmp_path):
    backup = LocalStorage(tmp_path / "backups")
    result = run(env, settings=Settings(backup_storage=str(backup.root)))
    assert result.status == "ok"
    assert backup.exists(result.snapshot_key)
    assert not env["media"].listing("snapshots/")
    assert last_snapshot_rows(env["conn"], backup)


def test_cloud_publish_requires_private_backup_setting(env):
    result = run(env, settings=Settings(media_storage="gs://public-media"))
    assert result.status == "failed"
    assert "VILF_BACKUP_STORAGE" in result.error
    assert not env["site"].listing()


def test_publish_rejects_media_bucket_as_backup(env):
    result = run(env, settings=Settings(media_storage="gs://same", backup_storage="gs://same"))
    assert result.status == "failed"
    assert "separate" in result.error


def test_first_publish_uploads_everything(env):
    conn, site, media = env["conn"], env["site"], env["media"]
    result = run(env, by_email="me@example.com")
    assert result.status == "ok" and result.error is None
    assert result.uploaded == len(site.puts) > 0
    assert (result.deleted, result.unchanged) == (0, 0)
    assert site.exists("places/test-place/index.html")
    assert site.exists("sitemap.xml") and site.exists("places.json")
    # cache policy follows the suffix
    puts = dict((k, cc) for k, _, cc in site.puts)
    assert puts["places/test-place/index.html"] == "public, max-age=3600"
    assert puts["places.json"] == "public, max-age=3600"
    assert puts["favicon.ico"] == "public, max-age=86400"
    # snapshot of exactly the rows that were rendered
    snaps = [k for k in media.listing() if k.startswith("snapshots/")]
    assert snaps == [result.snapshot_key]
    saved = json.loads(media.get(result.snapshot_key).decode())
    assert [r["slug"] for r in saved] == SLUGS
    assert not diff_rows(saved, repo.all_rows(conn))  # timestamps aside (published_at moved), the same rows
    # rows are now live
    rows = repo.all_rows(conn)
    assert not any(repo.is_dirty(r) for r in rows)
    assert len({r["published_at"] for r in rows if r["slug"] in ("draft-place", "bare-place")}) == 1
    # run row
    r = runs.recent(conn)[0]
    assert r["kind"] == "publish" and r["status"] == "ok" and r["by_email"] == "me@example.com"
    assert r["summary"] == f"{result.uploaded} uploaded, 0 deleted, 0 unchanged"
    assert r["snapshot_key"] == result.snapshot_key and r["id"] == result.run_id
    assert r["details"]["changes"]["added"] == SLUGS
    assert env["cdn"].calls == [["/*"]] and result.cdn_invalidated is True
    assert result.changes.added == SLUGS and result.changes.changed == {}
    assert result.seconds >= 0


def test_second_publish_is_noop(env):
    first = run(env)
    env["site"].puts.clear()
    second = run(env)
    assert second.status == "ok"
    assert (second.uploaded, second.deleted) == (0, 0)
    assert second.unchanged == first.uploaded
    assert env["site"].puts == []
    assert second.snapshot_key != first.snapshot_key
    assert len([k for k in env["media"].listing() if k.startswith("snapshots/")]) == 2
    assert not pending_diff(env["conn"], env["media"])
    assert not second.changes


def test_bookkeeping_failure_reports_partial_publish_and_retry(env, monkeypatch):
    mark = repo.mark_published

    def broken(*args, **kwargs):
        raise RuntimeError("bookkeeping failed")

    monkeypatch.setattr(repo, "mark_published", broken)
    result = run(env)
    assert result.status == "failed" and result.partially_applied
    assert result.uploaded > 0 and result.snapshot_key
    last = runs.recent(env["conn"])[0]
    assert last["details"]["partially_applied"]
    assert repo.is_dirty(repo.get(env["conn"], "draft-place"))
    monkeypatch.setattr(repo, "mark_published", mark)
    retried = run(env)
    assert retried.status == "ok" and retried.uploaded == 0
    assert not repo.is_dirty(repo.get(env["conn"], "draft-place"))


def test_bookkeeping_failure_inside_request_transaction(env, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bookkeeping failed")

    monkeypatch.setattr(repo, "mark_published", broken)
    with env["engine"].begin() as conn:
        result = publish(conn, media=env["media"], site=env["site"], settings=Settings(),
                         html_dir=env["root"] / "html", static_dir=env["root"] / "static",
                         about_path=env["root"] / "about.md", today=TODAY)
        assert result.status == "failed" and result.partially_applied
    with env["engine"].connect() as conn:
        assert runs.recent(conn)[0]["status"] == "failed"
        assert repo.is_dirty(repo.get(conn, "draft-place"))


def test_edit_changes_only_its_page_and_feeds(env):
    conn, site = env["conn"], env["site"]
    run(env)
    site.puts.clear()
    old_body = repo.get(conn, "test-place")["body"]
    repo.update(conn, "test-place", {"body": "\nGet the **larb**, it is the best thing here.\n"})
    result = run(env)
    assert result.status == "ok"
    uploaded = {k for k, _, _ in site.puts}
    assert "places/test-place/index.html" in uploaded
    assert "places/test-place.md" in uploaded
    assert "llms-full.txt" in uploaded
    for slug in SLUGS:
        if slug != "test-place":
            assert f"places/{slug}/index.html" not in uploaded
            assert f"places/{slug}.md" not in uploaded
    assert result.uploaded == len(uploaded)
    assert result.changes.changed == {"test-place": {"body": (old_body, "\nGet the **larb**, it is the best thing here.\n")}}
    assert not repo.is_dirty(repo.get(conn, "test-place"))


def test_stale_object_removed_and_unpublished_row_deleted(env):
    conn, site = env["conn"], env["site"]
    site.put("old/index.html", b"gone", content_type="text/html")
    repo.delete(conn, "draft-place")  # never published: allowed
    result = run(env)
    assert result.status == "ok" and result.deleted == 1
    assert not site.exists("old/index.html")
    assert not site.exists("places/draft-place/index.html")
    assert "draft-place" not in result.changes.added


def test_img_prefix_is_left_alone(env):
    site, root = env["site"], env["root"]
    (root / "static" / "img" / "food").mkdir(parents=True)
    (root / "static" / "img" / "food" / "cached.jpg").write_bytes(b"jpg")
    site.put("img/food/legacy.jpg", b"legacy", content_type="image/jpeg")
    result = run(env)
    assert result.status == "ok" and result.deleted == 0
    assert not site.exists("img/food/cached.jpg")
    assert site.exists("img/food/legacy.jpg")


def test_mass_delete_guard(env):
    conn, site = env["conn"], env["site"]
    run(env)
    junk = [f"junk/{i}.html" for i in range(MASS_DELETE_MIN + 5)]
    for key in junk:
        site.put(key, b"x", content_type="text/html")
    repo.update(conn, "test-place", {"body": "\nThe **larb** again.\n"})
    existing = len(site.listing())
    result = run(env)
    assert result.status == "failed"
    assert result.error == f"refusing to delete {len(junk)} of {existing} objects (use force)"
    assert result.deleted == 0 and result.uploaded == 0
    assert not result.partially_applied
    assert all(site.exists(k) for k in junk)
    assert "larb" not in site.get("places/test-place/index.html").decode()
    r = runs.recent(conn)[0]
    assert r["status"] == "failed" and "refusing to delete" in r["error"]
    assert r["summary"].startswith("refusing to delete")
    assert repo.is_dirty(repo.get(conn, "test-place"))  # not marked published on failure
    forced = run(env, force=True)
    assert forced.status == "ok" and forced.deleted == len(junk)
    assert not any(site.exists(k) for k in junk)


def test_put_failure_mid_upload(env, tmp_path):
    conn = env["conn"]
    flaky = RecordingStorage(tmp_path / "flaky", fail_on="places.json")
    flaky.put("stale/index.html", b"old", content_type="text/html")
    result = run(env, site=flaky)
    assert result.status == "failed"
    assert result.error == "upload of places.json failed: bucket exploded"
    assert result.partially_applied
    assert result.deleted == 0 and flaky.exists("stale/index.html")
    assert runs.recent(conn)[0]["status"] == "failed"
    assert all(repo.is_dirty(r) for r in repo.all_rows(conn) if r["slug"] == "draft-place")
    # the in-process lock was released and the running row finished
    assert runs.running(conn, "publish") is None
    assert run(env).status == "ok"


def test_invalid_row_fails_before_anything_written(env):
    conn, media, site = env["conn"], env["media"], env["site"]
    repo.update(conn, "test-place", {"body": "\nno dish highlighted here\n"})  # taste 2 needs a bold dish
    result = run(env)
    assert result.status == "failed"
    assert "test-place: taste: highlight a dish in bold" in result.error
    assert result.snapshot_key is None
    assert media.listing() == {} and site.listing() == {}
    assert repo.is_dirty(repo.get(conn, "test-place"))
    r = runs.recent(conn)[0]
    assert r["status"] == "failed" and r["summary"] == "1 validation problem(s)"
    assert env["cdn"].calls == []


def test_duplicate_blurb_fails(env):
    # names, phones and coordinates are UNIQUE in the database; the blurb rule is publish's alone
    conn = env["conn"]
    repo.update(conn, "bare-place", {"body": repo.get(conn, "test-place")["body"]})
    result = run(env)
    assert result.status == "failed" and "blurb" in result.error and "reused by" in result.error
    assert env["site"].listing() == {}


def test_publish_running(env):
    conn = env["conn"]
    runs.start(conn, "publish")
    with pytest.raises(PublishRunning, match="still running"):
        run(env)
    assert env["site"].listing() == {}


def test_in_process_lock(env):
    assert publish_mod._LOCK.acquire(blocking=False)
    try:
        with pytest.raises(PublishRunning):
            run(env)
    finally:
        publish_mod._LOCK.release()
    assert run(env).status == "ok"


def test_crash_finishes_run_as_failed(env, monkeypatch):
    conn = env["conn"]
    monkeypatch.setattr(publish_mod.render, "render_site", lambda *a, **k: 1 / 0)
    result = run(env)
    assert result.status == "failed" and "ZeroDivisionError" in result.error
    r = runs.recent(conn)[0]
    assert r["status"] == "failed" and "ZeroDivisionError" in r["error"]
    assert r["summary"].startswith("crashed: ZeroDivisionError")
    assert runs.running(conn, "publish") is None
    assert not publish_mod._LOCK.locked()
    monkeypatch.undo()
    assert run(env).status == "ok"


def test_running_row_is_visible_to_other_connections(env, monkeypatch):
    """The running row is committed before the work starts, so a second process would see it."""
    seen = []
    real_render = publish_mod.render.render_site

    def spy(*a, **k):
        with env["engine"].connect() as other:  # a fresh connection = another process
            seen.append(runs.running(other, "publish"))
        return real_render(*a, **k)

    monkeypatch.setattr(publish_mod.render, "render_site", spy)
    result = run(env)
    assert result.status == "ok"
    assert len(seen) == 1 and seen[0] is not None and seen[0]["id"] == result.run_id
    with env["engine"].connect() as other:
        assert runs.running(other, "publish") is not None  # finish is the caller's to commit
    env["conn"].commit()
    with env["engine"].connect() as other:
        assert runs.running(other, "publish") is None


def test_pending_diff(env):
    conn, media = env["conn"], env["media"]
    assert last_snapshot_rows(conn, media) == []
    assert pending_diff(conn, media).added == SLUGS
    run(env)
    assert [r["slug"] for r in last_snapshot_rows(conn, media)] == SLUGS
    assert not pending_diff(conn, media)
    repo.update(conn, "test-place", {"taste": 3})
    new = dict(FIXTURE[0])
    new.update(slug="new-place", name="New Place", lat=1.0, lon=1.0, phone=None, menu=None, place_id=None)
    repo.insert(conn, new)
    repo.insert(conn, {**new, "slug": "gone-again", "name": "Gone Again", "lat": 2.0, "lon": 2.0})
    repo.delete(conn, "gone-again")
    diff = pending_diff(conn, media)
    assert diff.added == ["new-place"] and diff.removed == []
    assert diff.changed == {"test-place": {"taste": (2, 3)}}


def test_indexnow_submitted_only_when_enabled(env, monkeypatch):
    posts = []

    def fake_post(url, **kw):
        posts.append((url, kw))
        return type("R", (), {"status_code": 202, "text": ""})()

    monkeypatch.setattr(requests, "post", fake_post)
    key = "0123456789abcdef0123456789abcdef"
    for old in (env["root"] / "static").glob("*.txt"):
        old.unlink()
    (env["root"] / "static" / f"{key}.txt").write_text(key)

    assert run(env, settings=Settings(indexnow=False), today=date(2026, 9, 6)).status == "ok"
    assert posts == []
    result = run(env, settings=Settings(indexnow=True), today=date(2026, 9, 6))
    assert result.status == "ok"
    assert len(posts) == 1
    url, kw = posts[0]
    assert url == publish_mod.indexnow.ENDPOINT
    assert kw["json"]["host"] == "vilf.org" and kw["json"]["key"] == key
    assert "https://vilf.org/places/draft-place/" in kw["json"]["urlList"]  # updated 2026-09-05
    assert "https://vilf.org/places/test-place/" not in kw["json"]["urlList"]  # updated 2026-09-01
    note = runs.recent(env["conn"])[0]["details"]["indexnow"]
    assert note.startswith("submitted ") and note.endswith("HTTP 202")

    def boom(url, **kw):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(requests, "post", boom)
    result = run(env, settings=Settings(indexnow=True), today=date(2026, 9, 6))
    assert result.status == "ok"
    assert runs.recent(env["conn"])[0]["details"]["indexnow"].startswith("failed:")


def test_cdn_failure_is_non_fatal(env):
    result = run(env, cdn=FakeCdn(fail=True))
    assert result.status == "ok" and result.cdn_invalidated is False
    r = runs.recent(env["conn"])[0]
    assert r["details"]["cdn_invalidated"] is False and r["details"]["cdn_error"] == "cdn down"
    assert run(env, cdn=None).cdn_invalidated is False


def test_gcp_cdn_invalidator_calls_client(monkeypatch):
    compute_v1 = pytest.importorskip("google.cloud.compute_v1")
    calls = []

    class FakeClient:
        def invalidate_cache(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(compute_v1, "UrlMapsClient", FakeClient)
    cdn = publish_mod.GcpCdnInvalidator("vilf-com", "vilf-lb")
    cdn.invalidate(["/*", "/img/food/x.jpg"])
    assert calls == [
        {"project": "vilf-com", "url_map": "vilf-lb", "cache_invalidation_rule_resource": {"path": "/*"}},
        {"project": "vilf-com", "url_map": "vilf-lb", "cache_invalidation_rule_resource": {"path": "/img/food/x.jpg"}},
    ]
