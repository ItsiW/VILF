# Ideas

Things to pursue, in priority order. The 2026-09-09 overhaul (branch cleanup, uv, Places
API, schema, SEO, AI discoverability, data reconciliation) is done, and the database
migration is complete. The `runs` table (visible on the admin's Sync page, or
`runs.last(conn, "audit")`) says when the data was last checked against Google.

## Database migration: complete

What exists (runbook and status in `infra/README.md`): a `places` + `runs` schema derived
from `scripts/schema.py` (`scripts/db.py`, `repo.py`), the importer from the markdown
archive, the FastAPI + htmx admin app (`app/`: Google lookup, edit, photo upload and crop,
relink, preview, sync, publish), `scripts/publish.py` (validate, snapshot, render, md5
mirror, mass-delete guard, CDN, IndexNow), JSON snapshots per publish with
`db restore-snapshot`, Cloud Run behind IAP deployed by CI, the media bucket on the CDN,
nightly cloud JSON/original-photo backups, and Mac database/original-photo backups.
The admin is at `admin.vilf.org`; the legacy reviews/photos and old deployment
credentials have been removed. Tests run offline, including an end-to-end test.

Deliberately not in v1:

- Row versioning or an edit history beyond the per-publish snapshots.
- Staged or draft photos: a photo change is live on the CDN as soon as it is saved, only
  the page that references it waits for Publish.
- Multi-user roles: `VILF_ADMIN_EMAIL` is one address.
- Per-visitor site features (accounts, comments, favourites). The public site stays static.

### Surfaced by the migration

- An `unlinked` boolean column so `fiji-airways` and `boba-binge` stop appearing in the
  audit and enrich "without a place_id" counts.
- The git packfile stays large after `git rm -r places raw/food`: history keeps every
  JPEG. Either accept it or rewrite history with `git filter-repo` once nobody has an
  old clone.
- `publish` uploads and invalidates the CDN before `mark_published` and the runs row; a
  crash in between leaves the site updated and the rows dirty, which the next publish
  reconciles. Fine, but a "publish partially applied" note on the Publish page would
  save a puzzled minute.
- The mass-delete guard (`max(25, 20%)` stale objects) is tuned for a site of ~550
  objects; revisit if the site grows or shrinks a lot.
- `--source files` and `scripts/importer.py` can go a release after the cleanup PR; the
  fixtures they use are small so there is no rush.
- Neon branches are a free staging database: `./vilf build --source db` against a branch
  URL previews a data change without a second bucket.

## Priority 2: New content surfaces

- **Cuisine-by-neighborhood pages** (e.g. vegan Chinese in Oakland) where there are three
  or more places. This is the query shape people search and ask assistants.
- **Short editorial summary** at the top of each neighborhood and cuisine index page so
  assistants have a quotable answer.
- **Hours on review pages.** `CONTACT_FIELDS` already returns them; not stored because
  they go stale. Could be fetched at build time for places with a `place_id`.

## Priority 3: Tooling follow-ups (cheap, from the overhaul's review notes)

- `check` could run `validate_place` first and list schema problems next to Google
  mismatches (a full pre-publish gate).
- `audit`: print problems as found so an interrupted run still yields output.
- `spatula`: `maps.app.goo.gl` short links aren't recognised (resolve the redirect or hint).
- `schema`: fixed-point floats for coordinates.
- `ruff` in the dev group; nothing lints today. Fonts and PNGs in `scripts/` belong in
  `scripts/assets/`.
- A shared `site_root` fixture in `tests/conftest.py`: `make_site_root` is copied in
  `test_build.py`, `test_publish.py` and `test_e2e.py`.
- `Dockerfile`/`deploy.yaml`: build with `--platform linux/amd64` explicitly so a local
  `docker build` on Apple Silicon matches CI.
Never upload database backups to the public media bucket. Private cloud backups
already protect against laptop loss; see `infra/backup/README.md`.

## Housekeeping (do opportunistically)

- **No staging environment for the site.** Publish goes straight to vilf.org. The admin's
  Preview covers single pages; a full preview would need a second bucket (or a Neon
  branch plus a local build, see above).
- **Map provider migration complete:** the homepage uses OpenFreeMap Liberty and
  pinned MapLibre 6.9.0, loaded as a deferred JavaScript module. No Mapbox account
  or token is needed. Retain provider attribution when changing the map style.
- Add a Dependabot config for github-actions and uv (setup-uv has no floating major tag).
- Add uv to the Nix dev shell.
- **Instagram poster.** Untouched, still Selenium (`uv sync --group instagram`) and still
  reads markdown files. Either move to the official Graph API and the database, or drop it.
- **Infra refactor from `origin/nix-infra`** (Tristan): cleaner auth scripts,
  shellcheck/shfmt hooks. Never merged; no Nix on this machine to test it. The tofu config
  is frozen anyway.
- **Multi-agent workflow speed.** The overhaul ran packages in four sequential phases
  because several edit `build.py`. The migration used one worktree per package and
  merged; keep that. Save the runner as a named workflow in `.claude/workflows/`.
