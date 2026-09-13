"""Read-only cloud check: restore JSON to temporary SQLite and regenerate one photo.

Run from the repository root: uv run python infra/backup/verify-restore.py
Production databases and buckets are never modified.
"""

import base64
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import photos, repo, snapshot
from scripts.db import init_db, make_engine
from scripts.storage import GCSStorage, LocalStorage


def main():
    backup = GCSStorage("vilf-backups")
    manifest = json.loads(backup.get("status/latest.json"))
    rows = snapshot.load_rows(backup.get(manifest["snapshot"]).decode())
    assert rows and len(rows) == manifest["places"]
    current = {b.name: b for b in backup.bucket.list_blobs(prefix="originals/")}
    for key, info in manifest["originals"].items():
        blob = current.get(key)
        if blob is None or str(blob.generation) != info["generation"]:
            blob = backup.bucket.get_blob(key, generation=int(info["generation"]))
        assert blob and blob.md5_hash == info["md5"], f"Missing/mismatched original: {key}"
    with TemporaryDirectory(prefix="vilf-restore-") as tmp:
        engine = make_engine(f"sqlite:///{tmp}/restore.db")
        init_db(engine)
        try:
            with engine.begin() as conn:
                repo.from_snapshot_rows(conn, rows, replace=True)
                assert snapshot.dump_rows(repo.all_rows(conn)) == snapshot.dump_rows(rows)
            row = next(r for r in rows if r.get("photo_key"))
            key = row["photo_key"]
            info = manifest["originals"][key]
            data = backup.bucket.blob(key, generation=int(info["generation"])).download_as_bytes()
            assert base64.b64encode(hashlib.md5(data).digest()).decode() == info["md5"]
            local = LocalStorage(Path(tmp) / "media")
            local.put(key, data, content_type="image/jpeg")
            variants = photos.recrop(local, row, row["photo_crop_y"])
            assert len(variants) == 4 and all(local.exists(k) for k in variants)
        finally:
            engine.dispose()
    print(f"Restore verified: {len(rows)} restaurants, {len(manifest['originals'])} original references,")
    print("one original downloaded/checksummed, all four variants regenerated. Production untouched.")


if __name__ == "__main__":
    main()
