import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from scripts import backup_history
from scripts.config import Settings
from scripts.storage import LocalStorage


@pytest.fixture
def client(tmp_path):
    def make(**kwargs):
        return TestClient(create_app(Settings(
            database_url=f"sqlite:///{tmp_path}/test.db",
            media_storage=str(tmp_path / "media"), site_storage=str(tmp_path / "site"), **kwargs)))
    return make


def test_unconfigured_and_navigation(client):
    response = client().get("/backups")
    assert response.status_code == 200
    assert "not configured" in response.text
    assert 'href="/backups"' in response.text


def test_auth_is_required(client):
    assert client(admin_email="itsi@vilf.org").get("/backups").status_code == 403


def test_success_and_stale_warning(client, tmp_path):
    storage = LocalStorage(tmp_path / "backups")
    storage.put("status/latest.json", json.dumps({
        "created_at": "2020-01-01T00:00:00+00:00", "places": 246,
        "originals": {"originals/test.jpg": {}}, "snapshot": "daily/test.json",
    }).encode(), content_type="application/json")
    response = client(backup_storage=str(storage.root)).get("/backups")
    assert "246 restaurants" in response.text
    assert "1 original photos" in response.text
    assert "Overdue" in response.text
    assert "daily/test.json" in response.text


@pytest.mark.parametrize("state,status", [("CONDITION_SUCCEEDED", "Succeeded"),
                                          ("CONDITION_FAILED", "Failed"),
                                          ("CONDITION_PENDING", "Running")])
def test_execution_states(state, status):
    assert backup_history.execution_row({"name": "jobs/x/executions/test", "conditions": [
        {"type": "Completed", "state": state}]})["status"] == status


def test_cloud_failures_are_not_reported_as_no_backups(client, monkeypatch):
    def fail(*args):
        raise RuntimeError("sensitive provider details")
    monkeypatch.setattr(backup_history, "storage_from_url", fail)
    monkeypatch.setattr(backup_history, "cloud_executions", fail)
    page = client(backup_storage="gs://backup", google_cloud_project="vilf-com").get("/backups").text
    assert "Could not read" in page and "Could not load cloud job history" in page
    assert "sensitive provider details" not in page
    assert "No successful backup recorded yet" not in page


def test_recent_history_escapes_failure_details(client, monkeypatch, tmp_path):
    monkeypatch.setattr(backup_history, "storage_from_url", lambda _: LocalStorage(tmp_path))
    monkeypatch.setattr(backup_history, "cloud_executions", lambda _: [{
        "name": "executions/failed-test", "startTime": "2026-09-12T01:00:00Z",
        "completionTime": "2026-09-12T01:00:05Z", "conditions": [
            {"type": "Completed", "state": "CONDITION_FAILED", "message": "<script>bad</script>"}],
    }])
    response = client(backup_storage="gs://backup", google_cloud_project="vilf-com").get("/backups")
    assert "Failed" in response.text and "failed-test" in response.text
    assert "&lt;script&gt;" in response.text
    assert "<script>bad" not in response.text


def test_missing_marker_is_explicit(client, tmp_path):
    response = client(backup_storage=str(tmp_path / "empty")).get("/backups")
    assert "No successful backup recorded yet" in response.text
    assert "No Mac backup report received yet" in response.text


def test_mac_failure_keeps_visible_last_success(client, tmp_path):
    storage = LocalStorage(tmp_path / "backups")
    storage.put("status/mac.json", json.dumps({
        "reported_at": "2020-01-02T04:15:30Z", "status": "Failed",
        "started_at": "2020-01-02T04:15:00Z", "finished_at": "2020-01-02T04:15:30Z",
        "last_success": {"finished_at": "2020-01-01T04:15:30Z",
                         "file": "vilf-test.dump", "bytes": 72078},
    }).encode(), content_type="application/json")
    page = client(backup_storage=str(storage.root)).get("/backups").text
    assert "Mac database backups" in page
    assert "Failed" in page and "vilf-test.dump" in page and "72078 bytes" in page
    assert "no successful Mac backup reported in over 36 hours" in page
    assert "not a live connection" in page
    assert "Jan 1, 2020 at 8:15 PM PST" in page
    assert "2019 at 8:15 PM PST" in page
    assert "All times are UTC" not in page


def test_fresh_mac_report_is_not_overdue(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.put("status/mac.json", json.dumps({
        "last_success": {"finished_at": "2026-09-12T04:15:30Z"},
    }).encode(), content_type="application/json")
    result = backup_history.overview(Settings(backup_storage=str(tmp_path)),
                                     now=datetime(2026, 9, 12, 12, tzinfo=UTC))
    assert result["mac"] and not result["mac_stale"]


@pytest.mark.parametrize("run_status,stale,errors,expected", [
    ("Succeeded", False, [], "Succeeded"),
    ("Failed", False, [], "Failed"),
    ("Running", False, [], "Running"),
    ("Succeeded", True, [], "Overdue"),
    ("Succeeded", False, ["Could not load cloud job history."], "Unknown"),
])
def test_backup_summary_statuses(client, monkeypatch, run_status, stale, errors, expected):
    from app.routes import backups

    monkeypatch.setattr(backups, "overview", lambda _: {
        "configured": True, "cloud": True, "errors": errors, "stale": stale,
        "latest": {"created_at": "2026-09-12T04:30:00Z", "places": 246,
                   "originals": {}, "snapshot": "daily/test.json"},
        "runs": [{"status": run_status, "started": "2026-09-12T04:30:00Z",
                  "completed": "", "name": "test", "message": ""}],
        "mac": {"status": run_status, "started_at": "2026-09-12T04:15:00Z",
                "finished_at": "2026-09-12T04:15:30Z", "reported_at": "2026-09-12T04:15:30Z",
                "last_success": {"finished_at": "2026-09-12T04:15:30Z", "file": "test.dump", "bytes": 12}},
        "mac_error": bool(errors), "mac_stale": stale,
    })
    page = client().get("/backups").text
    summary = page.split('<details class="panel backup-details">')[0]
    assert summary.count(f'backup-status-{expected.lower()}') == 2
    assert 'id="cloud-backup-heading"' in summary and 'id="mac-backup-heading"' in summary
    assert "test.dump" not in summary
    assert '<details class="panel backup-details" open' not in page
