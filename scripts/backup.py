"""Nightly private JSON + original-photo backup; never publishes or deletes media."""

import json
from datetime import UTC, datetime

from . import repo, snapshot
from .config import settings
from .db import make_engine
from .storage import GCSStorage


def copy_originals(source, target):
    """Copy changed originals server-side, pinning source and destination generations.

    Deleted source files are deliberately not removed from the backup. Replaced
    backup objects remain recoverable under the bucket's versioning policy.
    """
    existing = {b.name: b for b in target.list_blobs(prefix="originals/")}
    manifest = {}
    copied = 0
    for blob in source.list_blobs(prefix="originals/"):
        if not blob.md5_hash:
            raise ValueError(f"original has no checksum: {blob.name}")
        saved = existing.get(blob.name)
        if saved is None or saved.md5_hash != blob.md5_hash:
            saved = source.copy_blob(
                blob, target, blob.name,
                if_source_generation_match=blob.generation,
                if_generation_match=saved.generation if saved else 0,
            )
            copied += 1
        if saved.md5_hash != blob.md5_hash:
            raise ValueError(f"backup checksum mismatch: {blob.name}")
        manifest[blob.name] = {"generation": str(saved.generation), "md5": saved.md5_hash}
    return manifest, copied


def run_backup():
    s = settings()
    if not s.backup_storage or not s.backup_storage.startswith("gs://"):
        raise ValueError("VILF_BACKUP_STORAGE must name a private GCS bucket")
    if not s.media_storage.startswith("gs://") or s.backup_storage in (s.media_storage, s.site_storage):
        raise ValueError("backup, media and site storage must be separate buckets")
    media = GCSStorage(s.media_storage.removeprefix("gs://").rstrip("/"))
    backup = GCSStorage(s.backup_storage.removeprefix("gs://").rstrip("/"))
    backup.bucket.reload()
    if backup.bucket.iam_configuration.public_access_prevention != "enforced":
        raise ValueError("backup bucket must enforce public access prevention")
    if not backup.bucket.versioning_enabled:
        raise ValueError("backup bucket must enable object versioning")

    engine = make_engine(s.database_url)
    try:
        with engine.connect() as conn:
            rows = repo.all_rows(conn)
        if not rows:
            raise ValueError("refusing an empty backup; inspect the database target")
        originals, copied = copy_originals(media.bucket, backup.bucket)
        for row in rows:
            if row.get("photo_key") and row["photo_key"] not in originals:
                raise ValueError(f"missing original for {row['slug']}")
        # Detect edits during photo copying; retry the whole job rather than claiming
        # success for a mixed database snapshot. No production locks are needed.
        with engine.connect() as conn:
            if snapshot.dump_rows(repo.all_rows(conn)) != snapshot.dump_rows(rows):
                raise RuntimeError("restaurant data changed during backup; retry")
        now = datetime.now(UTC)
        prefix = f"daily/{now:%Y%m%dT%H%M%S.%f}Z"
        key = prefix + ".json"
        backup.put(key, snapshot.dump_rows(rows).encode(), content_type="application/json")
        manifest = {"schema_version": 1, "created_at": now.isoformat(), "snapshot": key,
                    "places": len(rows), "originals": originals}
        backup.put(prefix + ".manifest.json", json.dumps(manifest).encode(), content_type="application/json")
        # Written last: a success marker means both JSON and all originals exist.
        backup.put("status/latest.json", json.dumps(manifest).encode(), content_type="application/json")
        print(json.dumps({"severity": "INFO", "message": "VILF backup succeeded",
                          "snapshot": key, "places": len(rows), "originals": len(originals),
                          "copied": copied}), flush=True)
        return manifest
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_backup()
