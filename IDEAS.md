# Ideas

Things to pursue, in priority order. The 2026-09-09 overhaul (branch cleanup, uv, Places
API, schema, SEO, AI discoverability, data reconciliation) is done; what remains is below.
`AUDIT_LOG.md` says when the data was last checked against Google.

## Priority 1: Move reviews into a database

Starting from scratch (the old `database` branch was a SQLite + SQLAlchemy prototype that
rewired `build.py` to read from a `restaurants` table; it also had a markdown-to-DB
migration script, a backup script, and `pending/approved/rejected` status). Design
principles:

- `build.py` should keep consuming a plain list of dicts (or a JSON export) so templates
  and derived pages don't change and CI doesn't need DB credentials.
- `scripts/schema.py` is the schema: fields, validation, labels. Derive the table from it.
- Decide photo storage early: git, the GCS bucket, or blobs. `infra/deploy.sh` (never
  enabled) dumped images out of Postgres, which is the worst option.
- `place_id` is the natural primary key; `city`, `website`, `modified` already exist.
- Normalise cuisine and area so a rename doesn't silently change URLs. Rating labels are
  defined once in schema.py; render `map.html`'s legend from them too.
- Open questions: storage (SQLite in repo vs hosted Postgres like Neon/Supabase, both free
  at this size), how reviews get in (form? admin? CLI?), backups.

## Priority 2: New content surfaces

- **Cuisine-by-neighborhood pages** (e.g. vegan Chinese in Oakland) where there are three
  or more places. This is the query shape people search and ask assistants.
- **Short editorial summary** at the top of each neighborhood and cuisine index page so
  assistants have a quotable answer.
- **Hours on review pages.** `CONTACT_FIELDS` already returns them; not stored because
  they go stale. Could be fetched at build time for places with a `place_id`.

## Priority 3: Tooling follow-ups (cheap, from the overhaul's review notes)

- `check` with no arguments should mean every `places/*.md`; run `validate_place` first
  and list schema problems next to Google mismatches (a full pre-commit gate); the
  `--contact` search fallback bills five Enterprise results to use one (`max_results=1`).
- `audit`: accept file arguments; print problems as found so an interrupted run still
  yields output. Consider an `unlinked: true` frontmatter flag so `fiji-airways` and
  `boba-binge` stop appearing in the "without a place_id" count.
- `spatula`: `maps.app.goo.gl` short links aren't recognised (resolve the redirect or hint);
  iPhone HEIC photos need `pillow-heif` or a hint; compute the output path after the
  duplicate check so an aborted run leaves no empty directory.
- `schema`: wrap `yaml.YAMLError` in `ValueError` so callers catch one type; use
  `re.fullmatch`; anchor `visited` to `YYYY-MM-DD`; detect duplicate frontmatter keys;
  warn on a raw ` #` outside quotes (the truncation bug class); fixed-point floats.
- `places`: raise `PlacesError` (not `KeyError`) when a response lacks `id`; make `query`
  and `--id` mutually exclusive in `__main__`; clamp `max_results` to 1..20.
- `build.py`: parse `about.md` with schema's frontmatter regex instead of `split('---', 2)`;
  drop `format_phone_number`'s asserts (redundant with `PHONE_RE`); build into a temp dir
  and rename so two concurrent builds can't race; `cuisine_places` is unused.
- `llms.txt` review lines could also link `/places/<slug>.md`; escape `]` in names.
- tests: a `tests/conftest.py` for the shared fixture loader and no-network guard
  (duplicated in three files); the tmp-repo helper symlinks `static/` so builds write into
  the real image cache.
- `ruff` in the dev group; nothing lints today. `scripts/__init__.py` so it's a regular
  package. Fonts and PNGs in `scripts/` belong in `scripts/assets/`.

## Housekeeping (do opportunistically)

- **No staging environment.** Merging to `develop` is a production deploy. PRs now get a
  downloadable build artifact; a real preview URL would need a second bucket.
- **Mapbox access token is hardcoded in `html/map.html`** on a collaborator's account, and
  pins MapLibre to a 2021 version. Move to your own token or a free tile source
  (OpenFreeMap / Protomaps). Also `maplibre-gl.js` loads synchronously from unpkg; `defer`
  would help first paint more than anything else on the page.
- **deploy.yaml** still uses `google-github-actions/auth@v0` and `setup-gcloud@v0`
  (Node16-era): likeliest next CI breakage. Bump when you can watch a deploy. Add a
  Dependabot config for github-actions and uv (setup-uv has no floating major tag).
- **CDN invalidation is still manual** after each deploy (`gcloud compute url-maps
  invalidate-cdn-cache vilf-lb --path '/*'`; gcloud is installed and logged in on the Mac).
  Give the deploy service account the permission and add it as the last workflow step so
  changes show immediately instead of after an hour.
- **Vercel's GitHub app** emails about the repo on every push; disconnect it in Vercel if unwanted.
- `infra/deploy.sh` still pip-installs the deleted `requirements.txt`; delete it or port to
  uv once the database design settles. Add uv to the Nix dev shell.
- **Instagram poster.** Untouched, still Selenium (`uv sync --group instagram`). Either move
  to the official Graph API or drop it.
- **Infra refactor from `origin/nix-infra`** (Tristan): cleaner auth scripts,
  shellcheck/shfmt hooks. Never merged; no Nix on this machine to test it.
- **Multi-agent workflow speed.** The overhaul ran packages in four sequential phases
  because several edit `build.py`. Next time: give each package a git worktree and merge,
  use one critic + two reviewers + one fix round, medium effort for reviewers, and split
  `build.py` into modules first so packages don't collide. Save the runner as a named
  workflow in `.claude/workflows/`.
