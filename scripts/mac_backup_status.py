"""Report local pg_dump outcomes without uploading dumps or database credentials."""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from .storage import LocalStorage

KEY = "status/mac.json"


def record(storage, status, started, output=None, *, with_photos=False):
    try:
        previous = json.loads(storage.get(KEY))
    except (FileNotFoundError, ValueError):
        previous = {}
    now = datetime.now(UTC).isoformat()
    report = {"schema_version": 1, "reported_at": now,
              "status": status, "started_at": started,
              "finished_at": None if status == "Running" else now,
              "last_success": previous.get("last_success")}
    if status == "Succeeded":
        path = Path(output)
        report["last_success"] = {"finished_at": now, "file": path.name,
                                  "bytes": path.stat().st_size}
        if with_photos:
            photos = json.loads(storage.get("status/mac-photos.json"))
            if photos["started_at"] != started:
                raise ValueError("Photo report does not match this backup run")
            report["last_success"]["photos"] = photos
    storage.put(KEY, json.dumps(report).encode(), content_type="application/json")
    return report


def upload(bucket, data):
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(KEY)
    blob.cache_control = "no-store"
    blob.upload_from_string(data, content_type="application/json", timeout=15, retry=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--bucket", default="vilf-backups")
    parser.add_argument("--status", choices=["Running", "Succeeded", "Failed"])
    parser.add_argument("--started")
    parser.add_argument("--output")
    parser.add_argument("--with-photos", action="store_true")
    args = parser.parse_args()
    if args.upload:
        upload(args.bucket, sys.stdin.buffer.read())
        return
    if not args.status or not args.started:
        parser.error("--status and --started are required")
    root = Path(__file__).resolve().parents[1]
    report = record(LocalStorage(root / ".backups"), args.status, args.started, args.output,
                    with_photos=args.with_photos)
    try:
        subprocess.run(
            [sys.executable, "-m", "scripts.mac_backup_status", "--upload", "--bucket", args.bucket],
            input=json.dumps(report).encode(), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=30, check=True, cwd=root,
        )
    except (subprocess.SubprocessError, OSError):
        print("Warning: Mac backup status saved locally but cloud reporting failed; check ADC authentication.", file=sys.stderr)


if __name__ == "__main__":
    main()
