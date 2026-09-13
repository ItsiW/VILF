# Private cloud backups

VILF uses `gs://vilf-backups` (Standard, `us-west1`, public access prevention,
uniform bucket IAM, object versioning). Never grant public access to this bucket.
The admin's `VILF_BACKUP_STORAGE` points here, separately from public media.

## Contents and retention

- `daily/<UTC timestamp>.json`: every restaurant row, including unpublished text,
  crop position and timestamps. Expires after 30 days.
- `daily/<timestamp>.manifest.json`: matching original-photo generations/checksums.
- `originals/`: incremental server-side copies, not regenerated images. Previous
  versions expire 30 days after replacement. Source deletions are **not** mirrored:
  an accidentally removed original remains in the backup until explicitly pruned.
- `status/latest.json`: manifest of the last completely successful nightly backup.
- `snapshots/`: pre-publish JSON snapshots. These small files are retained so the
  last successful publish remains available for comparisons even after 30 days.

`lifecycle.json` controls retention; deletion is asynchronous. Soft delete is
disabled **only on this new backup bucket** because versioning retains originals.
The production media bucket's recovery settings are unchanged.

## Automatic job

Cloud Scheduler invokes Cloud Run job `vilf-backup` daily at 04:30 UTC (not tied to
the Mac). The job runs `python -m scripts.backup`, using the app image, 512 MiB,
one CPU, a 15-minute timeout, one task and one retry. It reads the existing database
secret and media bucket; it never publishes or modifies production rows/photos.
The app image does not contain local credentials, imported photos, or build output.
The normal GitHub deployment updates both admin and backup job images.

For manual Cloud Build submissions, use the repository's `.gcloudignore` (the
default), **not** `--ignore-file=.dockerignore`: their directory-matching rules
differ, and an unanchored `places` rule excludes `app/templates/places` from the
upload. `cloudbuild.yaml` and GitHub CI run `python -m scripts.check_image` inside
the built container before publishing the image. It renders admin pages with a
temporary SQLite database, without production credentials or data.

The admin's **Backups** tab summarizes Cloud and Mac status side by side, with
last-success timestamps. A failed latest run or unavailable status is not shown
as successful just because an older backup exists. Schedules, archive details
and up to 30 Cloud Run executions are in an expandable section. Cloud backups
are overdue after 30 hours. Refresh the page to update it. The admin service account has
`roles/run.viewer` on the backup job; the tab never starts jobs or restores data.

```bash
gcloud run jobs execute vilf-backup --region=us-west1 --project=vilf-com --wait
gcloud storage cat gs://vilf-backups/status/latest.json
uv run python infra/backup/verify-restore.py
```

Monitoring emails `itsi@vilf.org` after a failed execution or no successful
execution for 30 hours. `setup-alerts.py` creates/updates these policies. It uses
built-in metrics and PromQL, avoiding the 23.5-hour metric-absence limit.
Check email delivery when first setting this up; policy creation alone does not
prove that email reached the inbox.

## Mac status reporting

The launchd script `pg-backup.sh` reports start, success and failure to
`status/mac.json` in the private backup bucket. A local copy lives in
`.backups/status/mac.json`. The admin displays the last reported run, last
successful dump filename/size, and an overdue warning after 36 hours without a
reported success. It cannot tell whether the Mac is currently online.

Reporting uses this checkout's `.venv` and Google Application Default Credentials
(`gcloud auth application-default login`). Keep the checkout in the location
configured in the launchd plist. Upload attempts are limited to 30 seconds;
reporting failure warns in the Mac log but does not fail a successful dump.
Only metadata is uploaded, never the dump or its database URL. Dumps remain in
`~/Backups/vilf` for 30 days, scheduled at 04:15 Mac local time. Mac failure
details are in `~/Library/Logs/vilf-pg-backup.log`. Cloud alerts described above
do not monitor the Mac; the Mac overdue warning is on the dashboard only.

The same Mac job also copies `gs://vilf-media/originals/` to
`~/Backups/vilf/photos`. It verifies checksums, skips unchanged files, pins each
download to its listed cloud generation, and atomically replaces changed files.
Missing source files are not deleted locally. Photos have no automatic expiry;
only their latest copied version is kept locally (cloud version history remains
available for 30 days after replacement). Thumbnails are regenerated if needed.
A new Mac run reports success only after both the dump and photo copy finish.
These are sequential operations, not an atomic database/photo snapshot.

## Recovery

First run `verify-restore.py`: it restores all JSON rows into temporary SQLite,
checks original versions, downloads one original and regenerates its four variants.
It does not modify production. The Mac's separate nightly `pg_dump` additionally
preserves SQL schema and run history; JSON backups do not.

For actual recovery, choose a matching daily JSON and manifest. Download originals
using each manifest's **generation**, not whichever file currently has that name.
Restore the JSON into a deliberately selected database with
`./vilf db restore-snapshot /absolute/path/snapshot.json` (without `--publish`).
Restore originals to the selected media storage and use `scripts.photos.recrop`
with each row's saved `photo_crop_y` to regenerate variants. Validate the admin and
preview before explicitly publishing. A JSON restore alone does not restore photos.

Nightly backups have an approximately 24-hour recovery-point window. They are not
an atomic database-and-photo transaction; an edit during the job normally causes
the job to retry. A photo replaced before any successful backup cannot be recovered
from this bucket. Retain the existing media recovery policy and Mac backups.

## Cost

Expected to fit unused free allowances at current size, not a hard spending cap.
GCS storage/operations, Cloud Run, Scheduler and builds share billing-account quotas.
Originals occupy about 667 MiB; thumbnails are deliberately not duplicated.
As checked September 2026, Google says Monitoring alert charges start no sooner
than September 1, 2027; review pricing then. See
[GCS pricing](https://cloud.google.com/storage/pricing) and
[Monitoring pricing](https://cloud.google.com/products/observability/pricing).
