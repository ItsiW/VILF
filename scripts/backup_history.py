"""Read-only backup status and Cloud Run execution history for the admin."""

import json
from datetime import UTC, datetime, timedelta

from .storage import storage_from_url


def cloud_executions(project: str) -> list[dict]:
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    with AuthorizedSession(credentials) as session:
        response = session.get(
            f"https://run.googleapis.com/v2/projects/{project}/locations/us-west1/jobs/vilf-backup/executions",
            params={"pageSize": 30}, timeout=15,
        )
        response.raise_for_status()
        return response.json().get("executions", [])


def execution_row(execution: dict) -> dict:
    condition = next((c for c in execution.get("conditions", []) if c.get("type") == "Completed"), {})
    state = condition.get("state")
    if state == "CONDITION_SUCCEEDED":
        status = "Succeeded"
    elif state == "CONDITION_FAILED" or execution.get("completionTime"):
        status = "Failed"
    else:
        status = "Running"
    return {
        "name": execution["name"].rsplit("/", 1)[-1],
        "started": execution.get("startTime") or execution.get("createTime", ""),
        "completed": execution.get("completionTime", ""),
        "status": status,
        "message": condition.get("message", ""),
    }


def overview(settings, *, now=None) -> dict:
    result = {"configured": bool(settings.backup_storage), "latest": None,
              "stale": False, "runs": [], "errors": [], "cloud": False,
              "mac": None, "mac_stale": False, "mac_error": False}
    if not settings.backup_storage:
        return result
    try:
        storage = storage_from_url(settings.backup_storage)
        try:
            latest = json.loads(storage.get("status/latest.json"))
        except FileNotFoundError:
            latest = None
        if latest:
            created = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
            result["stale"] = (now or datetime.now(UTC)) - created > timedelta(hours=30)
            result["latest"] = latest
    except Exception:
        # Do not leak provider errors or connection/configuration details into HTML.
        result["errors"].append("Could not read the latest backup. Check backup storage permissions and cloud logs.")
    try:
        storage = storage_from_url(settings.backup_storage)
        try:
            mac = json.loads(storage.get("status/mac.json"))
        except FileNotFoundError:
            mac = None
        if mac:
            success = mac.get("last_success")
            result["mac_stale"] = not success or (now or datetime.now(UTC)) - datetime.fromisoformat(
                success["finished_at"].replace("Z", "+00:00")) > timedelta(hours=36)
            result["mac"] = mac
    except Exception:
        result["mac_error"] = True
    if settings.backup_storage.startswith("gs://") and settings.google_cloud_project:
        result["cloud"] = True
        try:
            result["runs"] = sorted(
                (execution_row(e) for e in cloud_executions(settings.google_cloud_project)),
                key=lambda r: r["started"], reverse=True,
            )
        except Exception:
            result["errors"].append("Could not load cloud job history. Backup status is unknown; check Cloud Run permissions and logs.")
    return result
