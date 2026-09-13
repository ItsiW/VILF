"""Offline regression tests for incremental, generation-pinned original backups."""

from types import SimpleNamespace
import json
from pathlib import Path

import pytest

from scripts.backup import copy_originals
from scripts import backup, repo
from scripts.config import Settings
from scripts.db import init_db, make_engine


def blob(name="originals/test.jpg", md5="abc", generation=1):
    return SimpleNamespace(name=name, md5_hash=md5, generation=generation)


class Bucket:
    def __init__(self, blobs=()):
        self.blobs = list(blobs)
        self.copies = []

    def list_blobs(self, prefix):
        return [b for b in self.blobs if b.name.startswith(prefix)]

    def copy_blob(self, source, target, name, **kwargs):
        self.copies.append((name, kwargs))
        saved = blob(name, source.md5_hash, 99)
        target.blobs.append(saved)
        return saved


def test_new_original_is_pinned_and_manifest_records_backup_generation():
    source, target = Bucket([blob()]), Bucket()
    manifest, copied = copy_originals(source, target)
    assert copied == 1
    assert manifest == {"originals/test.jpg": {"generation": "99", "md5": "abc"}}
    assert source.copies[0][1] == {"if_source_generation_match": 1, "if_generation_match": 0}


def test_unchanged_original_is_not_copied_and_deleted_files_are_preserved():
    source = Bucket([blob(), blob("img/not-an-original.jpg")])
    target = Bucket([blob(generation=2), blob("originals/deleted.jpg")])
    manifest, copied = copy_originals(source, target)
    assert copied == 0
    assert manifest["originals/test.jpg"]["generation"] == "2"
    assert len(target.blobs) == 2
    assert len(manifest) == 1


def test_replacement_uses_destination_precondition():
    source, target = Bucket([blob(md5="new", generation=3)]), Bucket([blob(generation=2)])
    _, copied = copy_originals(source, target)
    assert copied == 1
    assert source.copies[0][1] == {"if_source_generation_match": 3, "if_generation_match": 2}


def test_missing_checksum_fails_closed():
    with pytest.raises(ValueError, match="checksum"):
        copy_originals(Bucket([blob(md5=None)]), Bucket())


@pytest.fixture
def job(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path}/backup.db")
    init_db(engine)
    rows = json.loads((Path(__file__).parent / "fixtures/snapshot.json").read_text())
    with engine.begin() as conn:
        repo.from_snapshot_rows(conn, rows)
        rows = repo.all_rows(conn)
    source = Bucket([blob(r["photo_key"]) for r in rows if r["photo_key"]])
    target = Bucket()
    target.reload = lambda: None
    target.versioning_enabled = True
    target.iam_configuration = SimpleNamespace(public_access_prevention="enforced")
    writes = {}

    def put(key, data, **kwargs):
        writes[key] = data

    monkeypatch.setattr(backup, "GCSStorage", lambda name: SimpleNamespace(
        bucket=source if name == "media" else target, put=put))
    monkeypatch.setattr(backup, "make_engine", lambda url: engine)
    monkeypatch.setattr(backup, "settings", lambda: Settings(
        media_storage="gs://media", backup_storage="gs://backup", site_storage="gs://site"))
    return source, target, writes, rows


def test_complete_job_writes_success_marker_last(job):
    source, target, writes, rows = job
    manifest = backup.run_backup()
    assert list(writes)[-1] == "status/latest.json"
    assert json.loads(writes[manifest["snapshot"]]) == rows
    assert manifest["places"] == len(rows)
    assert len(manifest["originals"]) == sum(bool(r["photo_key"]) for r in rows)


@pytest.mark.parametrize("problem", ["public", "unversioned", "missing_photo"])
def test_unsafe_or_incomplete_backup_does_not_claim_success(job, problem):
    source, target, writes, _ = job
    if problem == "public":
        target.iam_configuration.public_access_prevention = "inherited"
    elif problem == "unversioned":
        target.versioning_enabled = False
    else:
        source.blobs = []
    with pytest.raises(ValueError):
        backup.run_backup()
    assert not writes
