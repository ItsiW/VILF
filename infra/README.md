# Infrastructure

Everything lives in GCP project `vilf-com` (number 952410211826), region
`us-west1`. Changes are made with `gcloud` through `infra/admin/setup-admin.sh`;
this README is the record of what exists.

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
- **`backup/`**: the nightly Postgres dump (`pg-backup.sh`) and its launchd job.

## What setup-admin.sh creates

Run `./infra/admin/setup-admin.sh <section>`. Every section says what it is
doing and can be re-run.

| section | creates or changes |
|---|---|
| `apis` | enables `run`, `artifactregistry`, `secretmanager`, `iap` |
| `buckets` | `gs://vilf-media` (us-west1, uniform access, 30 day soft delete, `allUsers` objectViewer); bumps `gs://vilf-org` soft delete to 30 days. The commented seed block copies `gs://vilf-org/img` into it |
| `cdn` | backend bucket `vilf-media`: CDN on, `CACHE_ALL_STATIC`, TTL 1 day / max 7 days, response header `X-Vilf-Backend: media` |
| `service-accounts` | runtime SA `vilf-admin@vilf-com.iam.gserviceaccount.com` |
| `roles` | `roles/storage.objectAdmin` for the runtime SA on both buckets (bucket level); custom project role `vilfCdnInvalidator` (`compute.urlMaps.invalidateCache` + `compute.globalOperations.get`, the latter so the invalidation operation can be polled) bound to it |
| `registry` | Artifact Registry repo `us-west1-docker.pkg.dev/vilf-com/vilf` (docker) with the cleanup policy: keep the newest 3 images, delete untagged after 7 days and, beyond the spec, tagged after 30 days (every CI push is sha-tagged, so without that rule the repo would grow forever; Cloud Run keeps its own copy of deployed images) |
| `secrets` | `vilf-database-url`, `vilf-google-places-api-key`, `vilf-maps-embed-api-key`, created empty, runtime SA gets `roles/secretmanager.secretAccessor` on each. Versions are added by hand (the section prints the commands) |
| `run` | Cloud Run service `vilf-admin`. Bootstraps it with Google's hello image if it does not exist (CI cannot create it: `run.developer` lacks actAs on the default compute SA), then sets scaling 0..1, 1 CPU, 1 GiB, concurrency 10, timeout 900 s, CPU boost, runtime SA, secrets as env vars, and the `VILF_*` env vars. Needs every secret to have a version |
| `iap` | grants `roles/run.invoker` to the IAP service agent (`service-952410211826@gcp-sa-iap.iam.gserviceaccount.com`, created with `gcloud beta services identity create`), turns on IAP with `--no-allow-unauthenticated`, and grants `roles/iap.httpsResourceAccessor` to `itsi@vilf.org`. Prints the admin URL |
| `deployer` | SA `vilf-deployer@`: `roles/run.developer` on the project, `roles/artifactregistry.writer` on the repo, `roles/iam.serviceAccountUser` on the runtime SA; creates a key into a temp file, stores it as GitHub secret `VILF_DEPLOY_KEY`, shreds the file |
| `urlmap` | exports `vilf-lb` to `admin/urlmap-before.yaml`, then adds path matcher `media` routing `/img/*` to backend bucket `vilf-media` (everything else stays on `vilf-org`). Prints the verification curls and rollback commands. Refuses to overwrite an existing export unless `FORCE=1` |
| `all-but-urlmap` | `apis buckets cdn service-accounts roles registry secrets deployer`, then tells you what to do next |

## Migration order

1. `./infra/admin/setup-admin.sh all-but-urlmap` (or the sections one by one:
   `apis`, `buckets`, `cdn`, `service-accounts`, `roles`, `registry`,
   `secrets`, `deployer`).
2. Add a version to each secret: `printf %s "$VALUE" | gcloud secrets versions add NAME --data-file=-`.
   The database URL is the SQLAlchemy form `postgresql+psycopg://...`.
3. `./infra/admin/setup-admin.sh run` (bootstraps the service and applies the settings).
4. `./infra/admin/setup-admin.sh iap`, then open the printed URL as itsi@vilf.org.
5. Merge to `develop`: `deploy.yaml` builds the image and replaces the hello image.
6. Seed the media bucket (commented block in the `buckets` section):
   `gcloud storage rsync -r gs://vilf-org/img gs://vilf-media/img`, then set
   `Cache-Control` on the copies. Check one object directly:
   `curl -sI https://storage.googleapis.com/vilf-media/img/food/<slug>.jpg`.
7. Publish from the admin app so the database, `gs://vilf-org` and
   `gs://vilf-media` agree.
8. **Cutover, last**: `./infra/admin/setup-admin.sh urlmap`. Verify with
   `curl -sI https://vilf.org/img/food/<slug>.jpg | grep -i -e HTTP -e x-vilf-backend`
   (the media backend answers with `X-Vilf-Backend: media`; propagation takes a
   few minutes) and `curl -sI https://vilf.org/ | grep HTTP`. Then
   `gcloud compute url-maps invalidate-cdn-cache vilf-lb --path '/*'`. Rollback:
   `gcloud compute url-maps remove-path-matcher vilf-lb --global --path-matcher-name=media`,
   or a full `gcloud compute url-maps import vilf-lb --global --source=infra/admin/urlmap-before.yaml`.
9. Retire the old deployer: `gh secret delete VILF_CREDS --repo ItsiW/VILF` and
   `gcloud iam service-accounts delete vilfer@vilf-com.iam.gserviceaccount.com`.

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

A launchd job dumps the database every night at 04:15 local time into
`~/Backups/vilf/vilf-<UTC timestamp>.dump` (pg_dump custom format, no owner or
privileges) and deletes dumps older than 30 days. One log line per run goes to
`~/Library/Logs/vilf-pg-backup.log`.

```bash
brew install libpq                                   # provides /opt/homebrew/opt/libpq/bin/pg_dump
mkdir -p ~/.config/vilf && printf 'DATABASE_URL=postgresql+psycopg://...\n' > ~/.config/vilf/backup.env
chmod 600 ~/.config/vilf/backup.env
cp infra/backup/com.itsi.vilf-pg-backup.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.itsi.vilf-pg-backup.plist   # load
launchctl kickstart -k gui/501/com.itsi.vilf-pg-backup                             # run now
launchctl print gui/501/com.itsi.vilf-pg-backup                                    # status
tail ~/Library/Logs/vilf-pg-backup.log
launchctl bootout gui/501/com.itsi.vilf-pg-backup                                  # remove
```

The plist hard-codes `/Users/itsi/git/vilf/infra/backup/pg-backup.sh`; if the
checkout moves, edit the path, `bootout` and `bootstrap` again. The script can
also be run by hand (`PG_DUMP=... ./infra/backup/pg-backup.sh` to override the
pg_dump path).

## Restore

```bash
/opt/homebrew/opt/libpq/bin/pg_restore --clean --if-exists --no-owner --no-privileges \
    --dbname "$DATABASE_URL" ~/Backups/vilf/vilf-<ts>.dump
```

Use the plain `postgresql://` form of the URL for libpq. Then open the admin app
and Publish so the site and media match the database again. Photo originals
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

The admin app does this itself after a publish (runtime SA role
`vilfCdnInvalidator`); this is for the rare case of editing the bucket by hand.
