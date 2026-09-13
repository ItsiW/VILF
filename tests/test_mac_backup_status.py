import json
import subprocess

import pytest

from scripts.mac_backup_status import KEY, record
from scripts.storage import LocalStorage
from scripts import mac_backup_status


def test_success_records_only_filename_and_size(tmp_path):
    dump = tmp_path / "vilf-test.dump"
    dump.write_bytes(b"private database contents")
    storage = LocalStorage(tmp_path / "status")
    report = record(storage, "Succeeded", "2026-09-12T04:15:00Z", dump)
    assert report["last_success"]["file"] == dump.name
    assert report["last_success"]["bytes"] == dump.stat().st_size
    assert "private database contents" not in storage.get(KEY).decode()
    assert str(tmp_path) not in storage.get(KEY).decode()


@pytest.mark.parametrize("status", ["Running", "Failed"])
def test_later_runs_preserve_last_success(tmp_path, status):
    dump = tmp_path / "test.dump"
    dump.write_bytes(b"dump")
    storage = LocalStorage(tmp_path / "status")
    previous = record(storage, "Succeeded", "2026-09-12T04:15:00Z", dump)
    report = record(storage, status, "2026-09-13T04:15:00Z")
    assert report["last_success"] == previous["last_success"]
    assert report["status"] == status
    assert bool(report["finished_at"]) == (status == "Failed")
    assert json.loads(storage.get(KEY)) == report


def test_reporting_failure_does_not_fail_backup(tmp_path, monkeypatch, capsys):
    storage = LocalStorage(tmp_path)
    monkeypatch.setattr(mac_backup_status, "LocalStorage", lambda _: storage)
    monkeypatch.setattr("sys.argv", ["report", "--status", "Failed", "--started", "2026-09-12T04:15:00Z"])

    def fail(*args, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired("upload", 30)

    monkeypatch.setattr(mac_backup_status.subprocess, "run", fail)
    mac_backup_status.main()
    assert json.loads(storage.get(KEY))["status"] == "Failed"
    assert "cloud reporting failed" in capsys.readouterr().err


def test_combined_success_requires_matching_photo_report(tmp_path):
    storage = LocalStorage(tmp_path)
    dump = tmp_path / "test.dump"
    dump.write_bytes(b"dump")
    storage.put("status/mac-photos.json", json.dumps({"started_at": "older", "originals": 246}).encode(),
                content_type="application/json")
    with pytest.raises(ValueError, match="does not match"):
        record(storage, "Succeeded", "newer", dump, with_photos=True)
    report = record(storage, "Succeeded", "older", dump, with_photos=True)
    assert report["last_success"]["photos"]["originals"] == 246
