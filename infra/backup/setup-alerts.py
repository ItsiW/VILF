"""Create/update VILF backup email alerts using ADC; no production data writes.

Run after the first successful Cloud Run job execution. Uses built-in metrics,
not a paid uptime check or a new custom metric.
"""

import google.auth
from google.auth.transport.requests import AuthorizedSession

PROJECT = "vilf-com"
BASE = f"https://monitoring.googleapis.com/v3/projects/{PROJECT}"
METRIC = 'run_googleapis_com:job_completed_execution_count{monitored_resource="cloud_run_job",project_id="vilf-com",location="us-west1",job_name="vilf-backup"'


def main():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(creds)

    def request(method, url, **kwargs):
        response = session.request(method, url, timeout=60, **kwargs)
        if not response.ok:
            raise RuntimeError(f"Monitoring request failed: {response.status_code} {response.text}")
        return response.json()

    channels = request("GET", BASE + "/notificationChannels").get("notificationChannels", [])
    channel = next((c for c in channels if c.get("type") == "email"
                    and c.get("labels", {}).get("email_address") == "itsi@vilf.org"), None)
    if channel is None:
        channel = request("POST", BASE + "/notificationChannels", json={
            "type": "email", "displayName": "VILF backup alerts",
            "labels": {"email_address": "itsi@vilf.org"}, "enabled": True,
        })
    existing = request("GET", BASE + "/alertPolicies").get("alertPolicies", [])
    queries = {
        "VILF backup stale (30 hours)":
            '(sum(sum_over_time(' + METRIC + ',result="succeeded"}[30h])) or vector(0)) < 1',
        "VILF backup execution failed":
            'sum(sum_over_time(' + METRIC + ',result="failed"}[15m])) > 0',
    }
    for name, query in queries.items():
        policy = {
            "displayName": name, "combiner": "OR", "enabled": True,
            "notificationChannels": [channel["name"]],
            "documentation": {"mimeType": "text/markdown", "content":
                "Check Cloud Run job `vilf-backup` in `vilf-com/us-west1` and "
                "`gs://vilf-backups/status/latest.json`. Do not publish or restore production "
                "to troubleshoot a backup failure. See infra/backup/README.md."},
            "conditions": [{"displayName": name, "conditionPrometheusQueryLanguage": {
                "query": query, "duration": "0s", "evaluationInterval": "300s",
            }}],
            "alertStrategy": {"autoClose": "86400s"},
        }
        old = next((p for p in existing if p["displayName"] == name), None)
        if old:
            policy["name"] = old["name"]
            result = request("PATCH", "https://monitoring.googleapis.com/v3/" + old["name"],
                             params={"updateMask": "displayName,combiner,enabled,notificationChannels,documentation,conditions,alertStrategy"}, json=policy)
        else:
            result = request("POST", BASE + "/alertPolicies", json=policy)
        print(name, result["name"])
    print("Email channel:", channel["name"], channel.get("verificationStatus", "unspecified"))


if __name__ == "__main__":
    main()
