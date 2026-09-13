# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

VILF (Vegans In Love with Food) is a static site of vegan restaurant reviews for the SF Bay Area at https://vilf.org. The source of truth is a database: one row per restaurant in a `places` table (Postgres on Neon in production, SQLite locally), holding the metadata that used to be YAML frontmatter plus the review body in markdown. A FastAPI + htmx admin app (`app/`) edits rows and photos and publishes: `scripts/publish.py` renders the whole site with the Jinja2 templates in `html/` and mirrors it into the site bucket `gs://vilf-org`. Photos live in the media bucket `gs://vilf-media` and are served at `vilf.org/img/...` because the load balancer routes `/img/*` to that bucket. Restaurant metadata is linked to Google Places by `place_id` and kept in sync through the CLI. There is no framework beyond FastAPI and no linter; `tests/` is an offline pytest suite that exercises the CLI, the app, the importer and publish against recorded fixtures.

The database cutover is complete. Legacy `places/*.md` and `raw/food/*.jpg` have been removed from the checkout but remain in Git history. Use current cloud/Mac backups for recovery, not a fresh import of stale reviews. The owner's local `.env` points to production Postgres and buckets; SQLite remains the isolated-test/development option. `IDEAS.md` tracks future work; `infra/README.md` records the migration. The old `AUDIT_LOG.md` is gone: maintenance and publish operations write to the `runs` table.

## Commands

All CLI entry points go through the `./vilf` wrapper (`uv run python -m scripts.cli`, works from any directory). Dependencies live in `pyproject.toml` (core, plus an `instagram` group for the poster and a `dev` group with pytest and httpx) and are locked in `uv.lock`: edit `pyproject.toml`, then `uv lock`; CI uses `uv sync --locked`. Python is pinned by `.python-version`. Every command reads `scripts/config.py` settings from the environment and `.env` (gitignored; `.env.example` lists every variable). Anything that talks to Google needs `GOOGLE_PLACES_API_KEY`.

```bash
uv sync                                  # deps into .venv (add --group instagram for the poster)
./vilf db init                           # create the tables in DATABASE_URL (default sqlite:///./vilf.db)
./vilf db import-markdown [--dry-run] [--replace]   # legacy recovery only; requires an archive from Git history
./vilf serve [--reload]                  # admin app at http://localhost:8000 (no IAP: you are VILF_DEV_USER)
./vilf build [--source db|files|snapshot] [--snapshot FILE] [--out build] [--copy-media DIR]   # static build into build/ (wiped first); exits 1 on bad data
python3 -m http.server 8080 --directory build   # serve the build; use localhost, not 0.0.0.0, or the map won't render
uv run pytest                            # ~560 offline tests including a real render and the e2e test

./vilf spatula -s 'Lion Dance Cafe'      # new review row: search Google, pick, prompt for ratings; body stays <REVIEW>
./vilf spatula --place-id ChIJ... --photo ~/photo.jpg   # skip the search; photo goes into media storage
./vilf check [SLUGS] --contact --fix     # compare (and correct) address/coords/phone/website against Google
./vilf enrich [SLUGS] [--dry-run] [--contact] [--force]   # link rows without a place_id (nearest match within 150 m), fill city
./vilf audit [SLUGS] --mark-closed       # flag permanently closed rows (closed: True); --no-log skips the runs row
./vilf publish [--force]                 # render the DB and mirror it into VILF_SITE_STORAGE (this is the deploy)
./vilf db snapshot [PATH]                # every row as JSON (stdout or PATH)
./vilf db restore-snapshot KEY_OR_PATH [--publish]   # replace every row from a media key (snapshots/...) or a file
uv run python -m scripts.places 'query' --details   # raw API lookup for debugging
```

`build --source db` (the default) renders the database and copies `<media>/img` into `build/img` when the media storage is a local directory; `--source files` is the legacy mode (markdown + `raw/food`, `static/img/` cache, lastmod from git) and `--source snapshot --snapshot FILE` renders a JSON dump. Nix users get a dev shell via `nix develop` (direnv through `.envrc`); its pre-commit hooks only cover Nix formatting, markdownlint and lychee, and block direct commits to `develop`. uv is not in that shell.

## Data model

`scripts/schema.py` is still the single source of truth for the review fields: the ordered field list, rating labels and colours, `load_place`, `validate_place`, `validate_unique`, `dump_frontmatter`, `write_place`. `scripts/db.py` derives the `places` table from `schema.FIELDS` (SQLAlchemy Core) and adds the columns below; `scripts/repo.py` is the only module that reads and writes rows, always in "snapshot format" (`tests/fixtures/snapshot.json`: schema fields plus `slug`, `body`, `photo_*`, ISO 8601 `Z` timestamps).

```yaml
name, cuisine, address, area, lat, lon, phone, menu, drinks, visited, taste, value, instagram_published, city, place_id, website, closed
+ slug, body, photo_key, photo_width, photo_height, photo_crop_y, created_at, updated_at, published_at
```

- Required: name, cuisine, address, area, lat, lon, drinks, visited, taste, value. `website` is Google's homepage URL and only a fallback: the page's single "Menu" link points at `menu`, or at `website` when there is no menu. Never render a separate website link.
- `taste` and `value` are integers 0–3 (CHECK constraints). Taste labels: DNR / SGFI / Good / Phenomenal. Value labels: Bad / Fine / Good / Phenomenal.
- `phone` is `+1` plus 10 digits or NULL. `menu` and `website` must start with http(s). `visited` is a date.
- If `taste >= 1` the body must bold at least one dish with `**...**`; the bolded dishes feed meta descriptions and alt text. The admin treats the missing bold as a warning while drafting; publish treats it as an error.
- `name`, `menu`, `phone`, `place_id` and the (lat, lon) pair are UNIQUE in the database; the first-50-words blurb rule is checked by `validate_rows` at publish time (and by `repo.validate_for_save` in the admin).
- `area` is the neighbourhood (drives `/neighborhoods/`); `city` is the real city (drives `addressLocality` in JSON-LD).
- **Dirty** = `published_at` is NULL or `updated_at > published_at` (`repo.is_dirty`); publish marks dirty rows published. `/places?filter=dirty` lists them.
- **Slugs are immutable** in the admin (readonly field). New slugs come from `spatula.slugify` + `repo.unique_slug` (`base`, `base-0`, `base-1`...; a base ending in `-<digits>` has that suffix replaced, quirk kept from the file era).
- **Only unpublished rows can be deleted** (`repo.delete` raises, the route answers 409). Anything that has been live is marked `closed: True` instead: the page stays online with a banner, out of the map, lists and llms.txt. Never delete reviews.
- Two rows are deliberately unlinked (no `place_id`) and always show in audit counts: `fiji-airways` (joke entry) and `boba-binge` (branch gone from Maps).
- `runs` table (`scripts/runs.py`): `kind` (publish, check, audit, import, restore), `scope`, `started_at`/`finished_at`, `status` running|ok|failed, `by_email`, `summary`, `details` JSON, `snapshot_key`, `error`. `runs.last(conn, kind)` answers "when was the data last audited".

## Media keys (scripts/photos.py, scripts/images.py)

Media storage (`VILF_MEDIA_STORAGE`, a directory or `gs://vilf-media`) holds `originals/<slug>.jpg` (the upload re-encoded as a plain JPEG, EXIF stripped, orientation applied), the four variants `img/food/<slug>.jpg|.webp` (1200x675) and `img/thumb/<slug>.jpg|.webp` (426x240), and `snapshots/<UTC stamp>.json` written by every publish. `set_photo` stores original + variants, `recrop` rewrites the variants at a new `crop_y` (0 top .. 1 bottom; ignored for photos 16:9 or wider), `delete_photo` removes all five keys. Publish never writes or deletes `img/` in site storage: the bucket serves `/img/*` from media, and the local `static/img/` cache must never be pushed.

## Admin app (app/)

`app/main.py: create_app(settings)` puts engine, media, site and the Jinja environment on `app.state` and includes every router in `app.routes.{places,photos,sync,publish}` that exists and exposes `router`. `app/deps.py` has `get_conn` (one `engine.begin()` per request), `get_media`, `get_site`, `get_settings`, `current_user` and `render(request, template, status_code=200, **ctx)` (`partial=True` on `HX-Request`; templates see `request`, `settings`, `user`, `partial`; globals `TASTE_LABELS`, `VALUE_LABELS`, `FILTERS`, `is_dirty`).

| route | does |
|---|---|
| `GET /` | redirect to `/places` |
| `GET /places?q=&filter=dirty\|closed\|nophoto` | list (`places/_table.html` partial for htmx) |
| `GET /places/new`, `POST /places/new/search`, `POST /places/new/pick` | Google lookup (name and city, or a Maps URL) → candidates with duplicate flags → prefilled form |
| `POST /places` | create (303 to `/places/{slug}?flash=created`; `street_in_slug` checkbox for chains) |
| `GET/POST /places/{slug}` | edit page (dirty/published/closed chips, Preview link) and save |
| `POST /places/{slug}/delete` | only while unpublished, else 409 |
| `GET /places/{slug}/preview` | the public page rendered with `html/place.html` |
| `POST /places/{slug}/relink` | `q` → candidates, `place_id` → take Google's location data (name stays) |
| `GET/POST /places/{slug}/photo`, `GET .../photo/preview?crop_y=`, `POST .../photo/crop`, `POST .../photo/delete` | photo panel: upload (JPEG/PNG/HEIC), crop slider, delete; CDN paths of the variants invalidated when configured |
| `GET /media/{key}` | streams a media object (thumbs and previews in the admin) |
| `GET /sync`, `GET /publish` | provided by `app/routes/sync.py` and `app/routes/publish.py` (check/audit/enrich over the DB, pending diff and Publish button); nav links exist in `base.html` |
| `GET /healthz` | unauthenticated `{"ok": true}` |

House style: `router = APIRouter(dependencies=[Depends(current_user)])`; `search_text` and `get_place` are imported at module level so tests monkeypatch `app.routes.places.search_text`; partial templates start with an underscore; flashes travel in `?flash=`.

**IAP rules** (`deps.current_user`): with both `X-Goog-IAP-JWT-Assertion` and `X-Goog-Authenticated-User-Email` present, the email (after `accounts.google.com:`) must equal `VILF_ADMIN_EMAIL` or the request is 403. With neither header and no `VILF_ADMIN_EMAIL` configured the request runs as `VILF_DEV_USER` (local dev). Any other combination is 403. `/healthz` and `/static` are open. `GOOGLE_MAPS_EMBED_API_KEY` is a browser key: it is written into the `<iframe src>` of the Maps preview, so it must be restricted by HTTP referrer, whereas `GOOGLE_PLACES_API_KEY` is a server key that never reaches the browser.

## Publish (scripts/publish.py)

`publish(conn, *, media, site, settings, cdn=None, by_email=None, force=False, today=None, html_dir='html', static_dir='static', about_path='about.md') -> PublishResult` does, in order:

1. `validate_rows` every row (`validate_place` + `validate_unique`); any problem fails the run before anything is written.
2. Write `snapshots/<stamp>.json` of the rows to media storage.
3. `render.render_site` into a temp dir (place pages, `/best/`, `/latest/`, `/cuisines/*`, `/neighborhoods/*` for areas with 3+ places, `places.geojson`, `sitemap.xml`, `robots.txt`, `llms.txt`, `llms-full.txt`, `places.json`, `places/<slug>.md`; the `Verdict:` line on each page is reused there).
4. Upload every file whose md5 differs from the site listing (16 threads; `max-age=3600` for html/json/geojson/txt/xml/md, `86400` otherwise; `img/` excluded), then delete stale keys unless there are more than `max(MASS_DELETE_MIN=25, 20%)` of them and `force` is false.
5. Invalidate the CDN (`/*`, non-fatal), `mark_published` the dirty rows, finish the `runs` row (details: counts, added/removed/changed diff against the last snapshot), and submit fresh sitemap URLs to IndexNow when `VILF_INDEXNOW=1`.

A `running` runs row is committed on its own connection first; a second publish within 15 minutes raises `PublishRunning`. Any exception becomes a failed runs row, never a crash. `pending_diff(conn, media)` and `last_snapshot_rows` back the admin's Publish page. The CLI passes `GcpCdnInvalidator(project, url_map)` when `GOOGLE_CLOUD_PROJECT` and `VILF_URL_MAP` are set.

## Config (scripts/config.py)

| env | local default | production |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./vilf.db` | Secret `vilf-database-url` (Neon pooled `postgresql://...?sslmode=require`; `db.py` switches the driver to psycopg) |
| `VILF_MEDIA_STORAGE` | `./.media` | `gs://vilf-media` |
| `VILF_SITE_STORAGE` | `./.site` | `gs://vilf-org` |
| `VILF_SITE_URL` | `https://vilf.org` | same |
| `GOOGLE_CLOUD_PROJECT` / `VILF_URL_MAP` | unset (CDN step skipped) | `vilf-com` / `vilf-lb` |
| `GOOGLE_PLACES_API_KEY` | unset | Secret `vilf-google-places-api-key` (server key) |
| `GOOGLE_MAPS_EMBED_API_KEY` | unset (map hidden) | Secret `vilf-maps-embed-api-key` (browser key) |
| `VILF_ADMIN_EMAIL` | unset (dev user) | `itsi@vilf.org` |
| `VILF_DEV_USER` | `dev@localhost` | unused |
| `VILF_INDEXNOW` | `0` | `1` |
| `PORT` | `8000` | container listens on 8080 |

`settings()` is cached; `Settings(...)` is constructed directly in tests. Empty values count as unset.

## Google Places integration

- `scripts/places.py`: thin client for Places API (New). `search_text` (Bay Area location bias) and `get_place`, `parse_place` into a `Place` dataclass, E.164 phones, `distance_m`. Field masks are explicit because billing follows the priciest field: `CORE_FIELDS` is Pro tier (id, name, address components, location, business status, Maps URL); `CONTACT_FIELDS` adds phone, website, hours and is Enterprise tier. Only request CONTACT when the caller asked for it. Free monthly quotas dwarf this site's volume.
- Pure cores, reused by the CLI and the admin: `cross_reference.check_place(meta, *, contact, fix, get, search) -> CheckResult`, `audit.audit_rows(rows, *, get, workers) -> AuditReport`, `enrich.enrich_meta`. `check --fix` never changes names, keeps unit/suite details in addresses (`same_street`), rounds coordinates to 7 decimals and logs a `check` run. `audit --mark-closed` sets `closed: True` on `CLOSED_PERMANENTLY` places and logs an `audit` run. `spatula` inserts a row (and the photo) through `repo`/`photos`.
- Tests never hit the network: fixtures in `tests/fixtures/places/` and an autouse guard in `tests/conftest.py` on `places.requests`.

## Other scripts

- `scripts/indexnow.py`: submits sitemap URLs modified in the last 2 days to IndexNow (Bing and friends; Google has no equivalent). Publish calls it; the public key lives in `static/<key>.txt`.
- `scripts/importer.py`: legacy archive recovery only. Refuses to run on a non-empty table without `--replace`, reports orphan photos and logs an `import` run.
- `scripts/instagram_poster.py`, `scripts/image_generator.py`, `scripts/instagram_scratch.ipynb`: Selenium bot posting reviews with `instagram_published: False`. Needs `uv sync --group instagram` and `scripts/credentials.json` (gitignored). Not wired into the CLI, fragile, still reads markdown files.

## Tests

`uv run pytest` runs everything offline in a few seconds. App tests build a `TestClient(create_app(Settings(database_url='sqlite:///<tmp>/t.db', media_storage=<tmp>/media, site_storage=<tmp>/site)))` and seed rows with `repo.from_snapshot_rows(conn, ROWS, replace=True)` from `tests/fixtures/snapshot.json` (6 rows). `tests/test_e2e.py` strings the system together: lookup → create → photo upload → crop through the app, then `publish()` twice against the same LocalStorage media and site. Publish tests build a tmp site root (symlinked `html/` and `about.md`, top-level `static/` files only) so the local `static/img/` cache stays out.

## Infra and deploy

- **Admin app**: Cloud Run service `vilf-admin` (`us-west1`, 0..1 instances, behind IAP, runtime SA `vilf-admin@vilf-com`). `.github/workflows/deploy.yaml` on push to `develop`: pytest, `docker build` and push to `us-west1-docker.pkg.dev/vilf-com/vilf/admin:<sha>`, `gcloud run deploy vilf-admin --image` (nothing else: env, secrets, scaling and IAP are owned by `infra/admin/setup-admin.sh`). It authenticates with the `VILF_DEPLOY_KEY` secret. `build.yaml` runs pytest on PRs. Merging to `develop` deploys the admin; the public site only changes when someone publishes.
- **Cutover complete**: CI deploys the admin, not restaurant content. Public content is published from the database; `/img/*` is served from the media bucket. Legacy files are recoverable from Git history but are no longer a live data source.
- **`infra/admin/setup-admin.sh <section>`**: `apis`, `buckets` (gs://vilf-media, soft delete on both buckets), `cdn` (backend bucket with `X-Vilf-Backend: media`), `service-accounts`, `roles` (objectAdmin on both buckets, custom `vilfCdnInvalidator`), `registry` (Artifact Registry with cleanup policy), `secrets`, `run` (bootstraps the service with the hello image, sets env and secrets), `iap`, `deployer` (`vilf-deployer@` + `VILF_DEPLOY_KEY`), `urlmap` (routes `/img/*` to the media bucket; exports `urlmap-before.yaml` first), `all-but-urlmap`. Re-runnable.
- **Frozen**: the 2024 Nix/OpenTofu config (`flake.nix`, `infra/*.nix`) created the project, `gs://vilf-org`, url map `vilf-lb`, certificate, DNS and the old `vilfer` service account (`VILF_CREDS`). Its state is encrypted to a departed collaborator's key: never run tofu.
- **Backups**: `infra/backup/pg-backup.sh` + launchd plist dump the Neon database nightly at 04:15 into `~/Backups/vilf/` (30 days kept). Restore with `pg_restore`, then publish.
- Manual CDN invalidation (publish does it itself): `gcloud compute url-maps invalidate-cdn-cache vilf-lb --path '/*'`.
- Migration status and the step-by-step runbook: `infra/README.md`.
