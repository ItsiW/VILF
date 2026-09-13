# Infrastructure

Everything lives in GCP project `vilf-com` (number 952410211826), region
`us-west1`. Changes are made with `gcloud` through `infra/admin/setup-admin.sh`;
this README is the record of what exists and, below, the migration runbook.

> **Cutover status (September 12, 2026 PT).** GitHub `develop` deploys the admin
> only. Public `/img/*` now routes to `vilf-media`; the explicit `admin.vilf.org`
> host rule still routes to the IAP-protected admin. Public pages remain in
> `vilf-org`. Database-driven publishing is verified, including Mini Potstickers.
> Legacy reviews/photos have been removed from the checkout (recoverable in Git
> history). Old image objects remain in the site bucket for rollback.

## What is here

- **2024 Nix/OpenTofu config (frozen)**: `default.nix`, `bucket.nix`,
  `network.nix`, `dns.nix`, `certificate.nix`, `server.nix`/`server.py`,
  generated into OpenTofu by canivete from `flake.nix`. It created the project,
  bucket `gs://vilf-org`, backend bucket `vilf-org`, url map `vilf-lb` with the
  HTTP to HTTPS redirect, the static IP, certificate map, DNS, and the `vilfer`
  service account whose key is the GitHub secret `VILF_CREDS`. Its tofu state is
  sops-encrypted to a former collaborator's age key (`.sops.yaml`), so **do not
  run tofu**: it cannot read the state and would try to recreate everything.
  The commented block in `server.nix` is a never-enabled Postgres-to-markdown
  deploy design.
- **`admin/setup-admin.sh`**: the admin app's cloud setup, one section per
  resource group (below). `admin/ar-cleanup.json` is its Artifact Registry
  cleanup policy. `admin/urlmap-before.yaml` appears after the `urlmap` section
  runs; it is the rollback record for the cutover and can be committed (no
  secrets in it).
- **[`admin/custom-domain.md`](admin/custom-domain.md)**: `admin.vilf.org` DNS,
  certificate, hostname routing, verification and rollback.
- **[`backup/`](backup/README.md)**: private cloud backups and monitoring, restore
  verification, plus the Mac Postgres dump (`pg-backup.sh`) and its launchd job.
- **Application config**: `scripts/config.py` (env vars, listed in
  `.env.example`), `Dockerfile` (uvicorn on 8080), `.github/workflows/`.

## What setup-admin.sh creates

Run `./infra/admin/setup-admin.sh <section>`. Every section says what it is
doing and can be re-run.

| section | creates or changes |
|---|---|
| `apis` | enables `run`, `artifactregistry`, `secretmanager`, `iap` |
| `buckets` | `gs://vilf-media` (us-west1, uniform access, 30 day soft delete, `allUsers` objectViewer); bumps `gs://vilf-org` soft delete to 30 days. The commented seed block (rsync from `gs://vilf-org/img`) is superseded by `./vilf db import-markdown`, step 5 below |
| `cdn` | backend bucket `vilf-media`: CDN on, `CACHE_ALL_STATIC`, TTL 1 day / max 7 days, response header `X-Vilf-Backend: media` |
| `service-accounts` | runtime SA `vilf-admin@vilf-com.iam.gserviceaccount.com` |
| `roles` | `roles/storage.objectAdmin` for the runtime SA on both buckets (bucket level); custom project role `vilfCdnInvalidator` (`compute.urlMaps.invalidateCache` + `compute.globalOperations.get`, the latter so the invalidation operation can be polled) bound to it |
| `registry` | Artifact Registry repo `us-west1-docker.pkg.dev/vilf-com/vilf` (docker) with the cleanup policy: keep the newest 3 images, delete untagged after 7 days and tagged after 30 days (every CI push is sha-tagged; Cloud Run keeps its own copy of deployed images) |
| `secrets` | `vilf-database-url`, `vilf-google-places-api-key`, `vilf-maps-embed-api-key`, created empty, runtime SA gets `roles/secretmanager.secretAccessor` on each. Versions are added by hand (the section prints the commands) |
| `run` | Cloud Run service `vilf-admin`. Bootstraps it with Google's hello image if it does not exist (CI cannot create it: `run.developer` lacks actAs on the default compute SA), then sets scaling 0..1, 1 CPU, 1 GiB, concurrency 10, timeout 900 s, CPU boost, runtime SA, secrets as env vars, and the `VILF_*` env vars. Needs every secret to have a version |
| `iap` | grants `roles/run.invoker` to the IAP service agent (`service-952410211826@gcp-sa-iap.iam.gserviceaccount.com`, created with `gcloud beta services identity create`), turns on IAP with `--no-allow-unauthenticated`, and grants `roles/iap.httpsResourceAccessor` to `itsi@vilf.org`. Prints the admin URL |
| `deployer` | SA `vilf-deployer@`: `roles/run.developer` on the project, `roles/artifactregistry.writer` on the repo, `roles/iam.serviceAccountUser` on the runtime SA; creates a key into a temp file, stores it as GitHub secret `VILF_DEPLOY_KEY`, shreds the file |
| `urlmap` | exports `vilf-lb` to `admin/urlmap-before.yaml`, then adds path matcher `media` routing `/img/*` to backend bucket `vilf-media` (everything else stays on `vilf-org`). Prints the verification curls and rollback commands. Refuses to overwrite an existing export unless `FORCE=1` |
| `all-but-urlmap` | `apis buckets cdn service-accounts roles registry secrets deployer`, then tells you what to do next |

## Migration runbook

In order. Each step has a verification and a rollback; do not start the next
step until the verification passes. Steps 4 to 8 should happen on the same day:
after step 4 CI no longer updates `gs://vilf-org`, so the public site is frozen
until the first Publish in step 8.

### 0. Prerequisites (by hand, once)

- **Neon**: create a project in `aws-us-west-2`, Postgres 17, database `vilf`.
  Copy two connection strings from the console: the **pooled** one (host
  `...-pooler...`) for the Cloud Run secret, the **direct** one for `pg_dump`
  and `pg_restore`. Keep both in plain libpq form,
  `postgresql://USER:PASSWORD@HOST/vilf?sslmode=require`, and export the direct
  one as `DIRECT_URL` for the commands below: `scripts/db.py` rewrites the
  driver to `postgresql+psycopg` itself, while `psql`/`pg_dump`/`pg_restore`
  reject the `+psycopg` suffix (`backup/pg-backup.sh` strips it just in case).
- **Maps Embed API key**: in the `vilf-com` console create an API key
  restricted to the *Maps Embed API* and to HTTP referrers
  `https://vilf-admin-*.run.app/*` and `http://localhost:8000/*`. This key is
  visible in the admin's page source, which is why it is separate from the
  Places key (a server key, API-restricted to Places API (New), never sent to a
  browser).
- **Local tools**: `gcloud auth login && gcloud auth application-default login`
  (ADC is what `./vilf` uses for `gs://` storage), `gh auth status`,
  `brew install libpq` (pg_dump/pg_restore at `/opt/homebrew/opt/libpq/bin`),
  `docker` only if you want to build the image locally.

Verify: `gcloud config get-value project` prints `vilf-com`;
`psql "$DIRECT_URL" -c 'select 1'` (with `/opt/homebrew/opt/libpq/bin/psql`)
answers.

### 1. Cloud resources and secrets

```bash
./infra/admin/setup-admin.sh all-but-urlmap      # apis buckets cdn service-accounts roles registry secrets deployer
printf %s "$POOLED_URL"      | gcloud secrets versions add vilf-database-url --data-file=-
printf %s "$PLACES_KEY"      | gcloud secrets versions add vilf-google-places-api-key --data-file=-
printf %s "$MAPS_EMBED_KEY"  | gcloud secrets versions add vilf-maps-embed-api-key --data-file=-
```

The sections can also be run one by one in that order. `deployer` stores
`VILF_DEPLOY_KEY` in the GitHub repo. The old `VILF_CREDS` and `vilfer`
service account were retired after cutover (see step 10).

Verify:

```bash
for s in vilf-database-url vilf-google-places-api-key vilf-maps-embed-api-key; do gcloud secrets versions list $s; done
gcloud storage buckets describe gs://vilf-media --format='value(softDeletePolicy.retentionDurationSeconds)'   # 2592000
gcloud compute backend-buckets describe vilf-media --format='value(enableCdn)'                                  # True
gh secret list --repo ItsiW/VILF | grep VILF_DEPLOY_KEY
```

Rollback (nothing public has changed yet): `gcloud secrets delete NAME`,
`gcloud compute backend-buckets delete vilf-media`, `gcloud storage rm -r gs://vilf-media`
then `gcloud storage buckets delete gs://vilf-media`,
`gcloud iam service-accounts delete vilf-admin@vilf-com.iam.gserviceaccount.com`
(and `vilf-deployer@`), `gcloud artifacts repositories delete vilf --location=us-west1`,
`gh secret delete VILF_DEPLOY_KEY --repo ItsiW/VILF`.

### 2. Cloud Run service with the hello image

CI can only *update* the service, so it is created here first, with Google's
hello image, and configured with the secrets and env vars.

```bash
./infra/admin/setup-admin.sh run
```

Verify: `gcloud run services describe vilf-admin --region=us-west1 --format='value(status.url)'`
prints a URL; `gcloud run services describe vilf-admin --region=us-west1 --format=yaml | grep -A1 -e DATABASE_URL -e VILF_SITE_STORAGE`
shows the secret and env wiring.

Rollback: `gcloud run services delete vilf-admin --region=us-west1`.

### 3. IAP

```bash
./infra/admin/setup-admin.sh iap
```

Verify: open the printed URL in a browser; it redirects to a Google sign-in and
`itsi@vilf.org` then sees the hello page. A different Google account gets IAP's
403 page. `curl -sI "$ADMIN_URL/healthz" | head -1` is anything but 200
(typically a 302 to accounts.google.com); a 200 with a JSON body means IAP is
off.

Rollback: `gcloud run services update vilf-admin --region=us-west1 --no-iap`
(the service is still not public: `--no-allow-unauthenticated` stays).

### 4. Merge the admin branch to `develop` (the single merge)

This is the one push to `develop`. It replaces `deploy.yaml` with the
image-only deploy, so the old rsync of `build/` stops for good.

```bash
gh pr create --base develop --head admin ...    # or merge locally and push
gh run watch                                    # "Deploy VILF admin": pytest, docker build/push, gcloud run deploy
gcloud run services describe vilf-admin --region=us-west1 --format='value(spec.template.spec.containers[0].image)'
```

Verify: the image shown ends in the merge commit's sha;
`gcloud artifacts docker images list us-west1-docker.pkg.dev/vilf-com/vilf/admin`
lists it; the admin URL now shows `/places` (empty list: the database is not
seeded yet). `curl -sI https://vilf.org/ | head -1` is still 200 (nothing
touched the site bucket).

Rollback: the hello image is still deployable
(`gcloud run deploy vilf-admin --region=us-west1 --image=us-docker.pkg.dev/cloudrun/container/hello`),
and reverting the merge on `develop` brings the rsync workflow back; the public
site was not modified by this step.

### 5. Seed Neon and the media bucket

`import-markdown` reads `places/*.md` and `raw/food/*.jpg` from the checkout,
writes each photo's EXIF-free original plus the four variants into media
storage and inserts the rows with their git dates as `published_at`, so nothing
is dirty afterwards. No byte copy from `gs://vilf-org/img` is needed (the
commented rsync in `setup-admin.sh` is obsolete). Four photos carry an EXIF
orientation (`chucks-takeaway`, `hometown-creamery`, `nopalito-to-go-window`,
`souvla`): the importer applies it, so they will render upright where the live
site currently shows them rotated. `raw/food/rheas-deli-market.jpg` has no
review and is reported as an orphan (decide in step 10).

```bash
export DATABASE_URL="$DIRECT_URL" VILF_MEDIA_STORAGE=gs://vilf-media
./vilf db init
./vilf db import-markdown --dry-run      # validates every file, lists orphans, writes nothing
./vilf db import-markdown                # a few minutes: 246 originals + 984 variants uploaded
```

Verify:

```bash
gcloud storage ls gs://vilf-media/originals/ | wc -l          # 246
gcloud storage ls 'gs://vilf-media/img/**' | wc -l            # 984
./vilf db snapshot | grep -c '"slug"'                         # 246
curl -sI https://storage.googleapis.com/vilf-media/img/food/lion-dance.webp | grep -i -e HTTP -e content-type -e cache-control
```

The admin's `/places` now lists 246 rows, `?filter=dirty` is empty and
`?filter=nophoto` is empty.

Rollback: `./vilf db import-markdown --replace` re-imports over a bad import;
`gcloud storage rm -r gs://vilf-media/originals gs://vilf-media/img` and
`psql "$DIRECT_URL" -c 'truncate places, runs'` empty everything.

### 6. Local equivalence check

Render the archive and the database side by side and compare, from a checkout
of the merged `develop`:

```bash
./vilf build --source files --out build-files                       # markdown + raw/food, lastmod from git
DATABASE_URL="$DIRECT_URL" VILF_MEDIA_STORAGE=gs://vilf-media ./vilf build --source db --out build-db
diff -r -x img build-files build-db
```

`img/` is excluded (file mode fills the local `static/img` cache, db mode copies
nothing when the media storage is a bucket). Expected residue, verified against
a SQLite import of the archive: exactly two files differ, `index.html` (the
order of the thumbnail preload list) and `sitemap.xml` (the order of the place
entries), because file mode keeps the directory's glob order and db mode sorts
by slug; `diff <(sort build-files/sitemap.xml) <(sort build-db/sitemap.xml)`
is empty and every `lastmod`/`dateModified` agrees because the importer copied
the git dates. Any other file in `diff -rq -x img build-files build-db` (a
missing page, a different verdict or image URL) is a bug to fix before
continuing.

Rollback: none needed; delete `build-files` and `build-db`.

### 7. Route `/img/*` to the media bucket

Completed September 12, 2026 PT. The first attempt was rolled back after temporary
`NoSuchBucket` responses. The same unchanged backend subsequently worked, so the
rule was reapplied and left to propagate. Verified all 984 image URLs return 200,
`X-Vilf-Backend: media`, and the exact generation listed in the media bucket.
The pre-change map is saved in `infra/admin/urlmap-before.yaml`, including
the admin host rule. Only `/img/*` was invalidated; no Publish or cloud deletion ran.
The 984 current variants are present. The four extra old variants named
`rheas-deli-market` are unused; the published review uses `rhea-s-deli-market`.

```bash
./infra/admin/setup-admin.sh urlmap
```

Verify (propagation takes a few minutes):

```bash
curl -sI https://vilf.org/img/food/lion-dance.jpg | grep -i -e HTTP -e x-vilf-backend   # 200, X-Vilf-Backend: media
curl -sI https://vilf.org/img/thumb/lion-dance.webp | grep -i -e HTTP -e x-vilf-backend
curl -sI https://vilf.org/ | grep HTTP                                                          # 200, no X-Vilf-Backend
gcloud compute url-maps invalidate-cdn-cache vilf-lb --path '/img/*'
```

Then open a few review pages and check the photos load (the four EXIF ones
now upright). Commit `infra/admin/urlmap-before.yaml`.

Rollback: `gcloud compute url-maps remove-path-matcher vilf-lb --global --path-matcher-name=media`,
or the full export `gcloud compute url-maps import vilf-lb --global --source=infra/admin/urlmap-before.yaml`.
The legacy `gs://vilf-org/img` objects are still in place until step 8, so the
site is whole either way.

### 8. First Publish and the legacy `img/` cleanup

Publish from the admin's **Publish** page (as `itsi@vilf.org`: the run is
recorded under that email and the runtime SA holds `vilfCdnInvalidator`). The
diff shows every place as added (there is no previous snapshot); this is
expected. The upload replaces every page in `gs://vilf-org` whose bytes differ
from the archive build and deletes nothing under `img/`. If the mass-delete
guard refuses (more than 25 stale objects outside `img/`), inspect the list and
publish again with force.

Fallback from the laptop: `DATABASE_URL="$DIRECT_URL" VILF_MEDIA_STORAGE=gs://vilf-media VILF_SITE_STORAGE=gs://vilf-org GOOGLE_CLOUD_PROJECT=vilf-com VILF_URL_MAP=vilf-lb VILF_INDEXNOW=1 ./vilf publish [--force]`.
It records `by_email=dev@localhost` and needs ADC with
`compute.urlMaps.invalidateCache`; `cdn: failed` is non-fatal (invalidate by
hand, below).

Publish never touches `img/` in the site bucket, so the legacy copies are
removed by hand, only after step 7's curls showed `X-Vilf-Backend: media`:

```bash
gcloud storage ls 'gs://vilf-org/img/**' | wc -l      # the old variants, 984 or so
gcloud storage rm -r gs://vilf-org/img
gcloud compute url-maps invalidate-cdn-cache vilf-lb --path '/*'
```

Verify:

```bash
curl -s https://vilf.org/places/lion-dance/ | grep -o 'Verdict: [^<]*'
curl -sI https://vilf.org/img/food/lion-dance.webp | grep -i -e HTTP -e x-vilf-backend
curl -s https://vilf.org/places.json | grep -c '"image": "https://vilf.org/img/food/'   # 246
curl -sI https://vilf.org/llms.txt | grep -i content-type                                # text/plain; charset=utf-8
curl -sI https://vilf.org/places/lion-dance.md | grep -i content-type               # text/markdown
```

The admin's Publish page shows the run as `ok` with its snapshot key, and
`gcloud storage ls gs://vilf-backups/snapshots/` lists it. A second Publish
reports 0 uploaded, 0 deleted.

Rollback: the site bucket has 30 day soft delete, so
`gcloud storage restore 'gs://vilf-org/**'` (or per object) brings back the
pre-publish pages and the legacy `img/`; combine with the url map rollback from
step 7. The pre-cutover deploy can also be reproduced from a checkout of the
last markdown commit: `./vilf build --source files && gsutil -m rsync -R -d build gs://vilf-org`.

### 9. Nightly backups

```bash
mkdir -p ~/.config/vilf && printf 'DATABASE_URL=%s\n' "$DIRECT_URL" > ~/.config/vilf/backup.env
chmod 600 ~/.config/vilf/backup.env
cp infra/backup/com.itsi.vilf-pg-backup.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.itsi.vilf-pg-backup.plist
launchctl kickstart -k gui/501/com.itsi.vilf-pg-backup
tail -1 ~/Library/Logs/vilf-pg-backup.log      # "<ts> ok vilf-<ts>.dump N bytes, pruned 0"
```

Details and restore in *Backups* below. Rollback: `launchctl bootout gui/501/com.itsi.vilf-pg-backup`.

### 10. Legacy file cleanup

Completed in the working tree September 12, 2026 PT, after successful public
publishing and fresh backups. All 246 legacy review slugs exist in the 247-row
database; the extra restaurant is Mini Potstickers. The unused `rheas-` photo
was discarded separately; the active `rhea-s-` original remains in media/backups.

Verification before removal:

- Cloud snapshot `daily/20260913T022104.888893Z.json` matched all production rows;
  restored to temporary SQLite and regenerated four variants from an original.
- Mac dump `vilf-20260913T022049Z.dump` fully decoded with 247 restaurant rows,
  including Mini Potstickers' September 7 visit date.
- All 247 Mac originals matched the cloud backup's MD5 checksums.

`places/` and `raw/food/` are no longer required by the admin or publishing.
Legacy importer/file-build support remains for recovery and fixture tests.
The old standalone Instagram scripts still require the archive and are not
part of the supported database workflow. Git history retains the removed
files, so this cleanup does not shrink historical clone size. Roll back the
file deletion with a revert after commit, or recover files from the preceding
commit into a separate archive directory.

The file cleanup did not delete database rows, media objects, cloud backups,
or Git history.

### 11. Retire the legacy deployment identity

Completed September 12, 2026 PT after the new GitHub deployment succeeded.
The active workflows use `VILF_DEPLOY_KEY`; Cloud Run admin, backup job, and
Scheduler use their dedicated newer service accounts. No `vilfer` activity
appeared in the available audit logs for the preceding 30 days; this is not
a guarantee that every historical data-access event was logged.

- Disabled `vilfer@vilf-com.iam.gserviceaccount.com`, removed its
  `roles/storage.objectAdmin` binding on `gs://vilf-org`, then deleted it.
- Deleted the GitHub Actions secret `VILF_CREDS`.
- Retained `VILF_DEPLOY_KEY`. Subsequently deleted `CLIMAX_VILF_SA_KEY`,
  the obsolete 2022 GitHub credential for `climax-vilf-bucket`, replaced in 2024.
  Its underlying Google key was not identified or revoked.

Retired account unique ID: `102747106945516708717`. Its one user-managed key
was `41766467194d30ada4633432ed18324945d9f909`. The deleted GitHub secret cannot
be retrieved. Do not recreate the legacy identity; use the current deployer.
The frozen Nix definitions still describe the retired resources: do not run
OpenTofu or use that old configuration to restore infrastructure.

### Deployment credential packaging

Docker images are built and smoke-tested before GitHub authentication. All three
ignore files exclude `gha-creds-*.json`; the image smoke check rejects credential
files and `.env`. During September 12 cleanup, the old deployer key
`b0dee6f222c9b2ed158cf022fe0d5f84258df808` was disabled and replaced in
`VILF_DEPLOY_KEY` because previous Docker builds could include the auth action's
generated credential file. Old images must not be treated as clean artifacts;
the retired key must remain unusable. Never print credentials in build logs.

## CI

- `.github/workflows/build.yaml` (pull requests to `develop`): `uv sync` and
  `pytest`. The render tests cover the site build, so there is no build
  artifact any more.
- `.github/workflows/deploy.yaml` (push to `develop`): pytest, `docker build`
  and push to `us-west1-docker.pkg.dev/vilf-com/vilf/admin:<sha>`, then
  `gcloud run deploy vilf-admin --image ...` with no other flags. It
  authenticates with `VILF_DEPLOY_KEY`. Merging to `develop` deploys the admin
  app; the public site is only touched when someone clicks Publish there.

## Backups

Cloud backups are now the primary automatic copy; see [backup/README.md](backup/README.md)
for the private bucket, daily Cloud Run job, retention, alerts and restore checks.
The Mac job below is an additional independent copy.

A launchd job dumps the database every night at 04:15 local time into
`~/Backups/vilf/vilf-<UTC timestamp>.dump` (pg_dump custom format, no owner or
privileges) and deletes dumps older than 30 days. One log line per run goes to
`~/Library/Logs/vilf-pg-backup.log`.

```bash
launchctl print gui/501/com.itsi.vilf-pg-backup                                    # status
launchctl kickstart -k gui/501/com.itsi.vilf-pg-backup                             # run now
launchctl bootout gui/501/com.itsi.vilf-pg-backup                                  # remove
```

The plist hard-codes `/Users/itsi/git/vilf/infra/backup/pg-backup.sh`; if the
checkout moves, edit the path, `bootout` and `bootstrap` again. The script can
also be run by hand (`PG_DUMP=... ./infra/backup/pg-backup.sh` to override the
pg_dump path). Every publish also writes a JSON snapshot of the rows to
`gs://vilf-backups/snapshots/`, restorable with `./vilf db restore-snapshot KEY` when
`VILF_BACKUP_STORAGE=gs://vilf-backups`. Do not publish until recovery is verified.

## Restore

```bash
/opt/homebrew/opt/libpq/bin/pg_restore --clean --if-exists --no-owner --no-privileges \
    --dbname "$DIRECT_URL" ~/Backups/vilf/vilf-<ts>.dump
```

`DIRECT_URL` is the plain `postgresql://` form from step 0 (libpq rejects
`postgresql+psycopg://`). Verify the database and restore matching original-photo
versions/regenerate variants before opening the admin and explicitly publishing.
Restoring rows or publishing does not itself restore photo bytes. Photo originals
live in `gs://vilf-media` (30 day soft delete, restorable with
`gcloud storage restore`) and are not part of the dump.

## Rotating the deployer key

```bash
gcloud iam service-accounts keys list --iam-account=vilf-deployer@vilf-com.iam.gserviceaccount.com --managed-by=user
./infra/admin/setup-admin.sh deployer      # re-applies the IAM bindings, creates a new key, overwrites VILF_DEPLOY_KEY
gcloud iam service-accounts keys delete OLD_KEY_ID --iam-account=vilf-deployer@vilf-com.iam.gserviceaccount.com
```

Keys are only ever written to a temp file that is shredded right after
`gh secret set`. `--managed-by=user` hides the Google-managed keys, which
cannot be deleted.

## Manual CDN invalidation

```bash
gcloud compute url-maps invalidate-cdn-cache vilf-lb --path '/*'
```

The admin app does this itself after a publish and after a photo change
(runtime SA role `vilfCdnInvalidator`); this is for the rare case of editing a
bucket by hand.
