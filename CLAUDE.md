# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

VILF (Vegans In Love with Food) is a static site of vegan restaurant reviews for the SF Bay Area, deployed to https://vilf.org. Content is one markdown file per restaurant in `places/`, with a YAML frontmatter block for metadata and the review body below it. A Python build script renders everything into `build/` via Jinja2 templates. Restaurant metadata is linked to Google Places by a `place_id` and kept in sync with the Places API through the CLI. There is no framework and no linter; `tests/` is a pytest suite that runs the real build and exercises every CLI command offline against recorded API fixtures.

`IDEAS.md` tracks future work. The next big project is moving reviews out of markdown into a database, started from scratch. `AUDIT_LOG.md` records when the data was last checked against Google.

## Commands

All CLI entry points go through the `./vilf` wrapper (`uv run python -m scripts.cli`, works from any directory). Dependencies live in `pyproject.toml` (core, plus an `instagram` group for the poster and a `dev` group with pytest) and are locked in `uv.lock`: edit `pyproject.toml`, then `uv lock`; CI uses `uv sync --locked`. Python is pinned by `.python-version`. Anything that talks to Google needs `GOOGLE_PLACES_API_KEY` in `.env` (gitignored; see `.env.example`).

```bash
uv sync                                  # deps into .venv (add --group instagram for the poster)
./vilf build                             # full site build into build/ (wipes it first); exits 1 on bad data
uv run pytest                            # ~350 offline tests including a real build
python3 -m http.server 8080 --directory build   # serve locally; use localhost, not 0.0.0.0, or the map won't render

./vilf spatula -s 'Lion Dance Cafe'      # new review: search Google, pick, prompt for ratings, write places/<slug>.md
./vilf spatula --place-id ChIJ... --photo ~/photo.jpg   # skip the search; drop the photo into raw/food/<slug>.jpg
./vilf check --contact --fix places/*.md # compare (and correct) address/coords/phone/website against Google
./vilf enrich                            # link reviews without a place_id (nearest match within 150 m), fill city
./vilf audit --delete                    # delete permanently closed reviews + photos; report temporary closures
uv run python -m scripts.places 'query' --details   # raw API lookup for debugging
```

Nix users get a dev shell via `nix develop` (direnv through `.envrc`); its pre-commit hooks only cover Nix formatting, markdownlint and lychee, and block direct commits to `develop`. uv is not in that shell yet.

## Data model (scripts/schema.py)

`schema.py` is the single source of truth: the ordered field list, rating labels and colours, `load_place`, `validate_place`, `validate_unique`, `dump_frontmatter`, `write_place`. Every command reads and writes place files through it, so files stay in canonical key order with `True`/`False` booleans and quoted `visited`/`phone`.

```yaml
name, cuisine, address, area, lat, lon, phone, menu, drinks, visited, taste, value, instagram_published, city, place_id, website
```

- Required: name, cuisine, address, area, lat, lon, drinks, visited, taste, value. The rest are optional; `city`, `place_id` and `website` are only written when set.
- `taste` and `value` are integers 0–3. Taste labels: DNR / SGFI / Good / Phenomenal. Value labels: Bad / Fine / Good / Phenomenal.
- `phone` is `+1` plus 10 digits or empty. `menu` and `website` must start with http(s). `visited` is a quoted ISO date.
- If `taste >= 1` the body must bold at least one dish with `**...**`; the bolded dishes feed meta descriptions and alt text.
- `name`, `menu`, `phone`, the (lat, lon) pair, and the first 50 words of the body must be unique across all places.
- `area` is the neighbourhood (drives `/neighborhoods/`); `city` is the real city (drives `addressLocality` in JSON-LD). A YAML value containing ` #` must be quoted or it is silently truncated as a comment; the writer does this for you.
- Two files are deliberately unlinked (no `place_id`) and always show in audit counts: `fiji-airways` (joke entry) and `boba-binge` (branch gone from Maps).

## Build pipeline (scripts/build.py)

`build_vilf` is one long function; later stages consume the `places` list built by the place loop.

1. **Images.** `raw/food/<slug>.jpg` → 1200x675 JPEG+WebP in `static/img/food/` and 426x240 thumbs in `static/img/thumb/` (asserts aspect ≤ 16:9). Existing outputs are skipped, so `static/img/` (gitignored) is a cache; delete it to regenerate.
2. **`static/` is copied to `build/`.**
3. **Place pages.** `schema.load_place` + `validate_place` per file; problems print as `<file>.md <message>` and the build exits 1 at the end if any occurred. The food image is found by slug, so `raw/food/<slug>.jpg` must match the filename. Each place gets `modified` from one `git log` call (fallback: `visited`), used for sitemap lastmod and JSON-LD dateModified.
4. **Derived pages**: `/best/` (taste, value, slug), `/latest/`, `/cuisines/*`, `/neighborhoods/*` (areas with 3+ places), `places.geojson` for the map, `sitemap.xml`, `robots.txt`.
5. **AI-readable outputs**: `llms.txt`, `llms-full.txt`, `places.json`, and `places/<slug>.md` per review (linked from each page with `rel=alternate`). A plain-text `Verdict:` line is rendered on each review and reused there.

Templates in `html/` extend `base.html` (nav, CSS, deferred Google Analytics, an `extra_head` block). `map.html` is the homepage (MapLibre reading `/places.geojson`). `place.html` carries the JSON-LD Restaurant and Article blocks; free-text values go through `| tojson`.

## Google Places integration

- `scripts/places.py`: thin client for Places API (New). `search_text` (Bay Area location bias) and `get_place`, `parse_place` into a `Place` dataclass, E.164 phones, `distance_m`. Field masks are explicit because billing follows the priciest field: `CORE_FIELDS` is Pro tier (id, name, address components, location, business status, Maps URL); `CONTACT_FIELDS` adds phone, website, hours and is Enterprise tier. Only request CONTACT when the caller asked for it. Free monthly quotas dwarf this site's volume.
- `scripts/spatula.py` (new reviews), `scripts/cross_reference.py` (`check`), `scripts/enrich.py`, `scripts/audit.py`, `scripts/auditlog.py` build on it. `check --fix` never changes names, keeps unit/suite details in addresses (`same_street`), and rounds coordinates to 7 decimals. `audit --delete` removes only `CLOSED_PERMANENTLY` places.
- Tests never hit the network: fixtures in `tests/fixtures/places/` and an autouse guard on `places._request`.

## Other scripts

- `scripts/indexnow.py`: after deploy, submits sitemap URLs modified in the last 2 days to IndexNow (Bing and friends; Google has no equivalent). The public key lives in `static/<key>.txt`.
- `scripts/instagram_poster.py`, `scripts/image_generator.py`, `scripts/instagram_scratch.ipynb`: Selenium bot posting reviews with `instagram_published: False`. Needs `uv sync --group instagram` and `scripts/credentials.json` (gitignored). Not wired into the CLI, fragile, untouched by the 2026 overhaul.

## Deploy and infra

- GitHub Actions: PRs to `develop` run pytest and the build and upload `build/` as a 7-day artifact. Pushes to `develop` build with full git history (for lastmod), `gsutil rsync` to `gs://vilf-org`, fix Content-Type on the text/markdown outputs, and ping IndexNow. So merging to `develop` is a production deploy.
- CDN cache invalidation is manual: `gcloud compute url-maps invalidate-cdn-cache vilf-lb --path /`.
- `infra/` is OpenTofu generated from Nix (`flake.nix` via canivete): GCP project `vilf-com`, bucket, load balancer, certificate, DNS, and the service account whose key is the `VILF_CREDS` secret. `infra/deploy.sh` is a never-enabled Postgres-to-markdown deploy script that still references the deleted `requirements.txt`; it is the closest prior art for the database migration.
