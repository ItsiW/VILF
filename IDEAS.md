# Ideas

Things to pursue, in priority order. Cleaned up all old branches on 2026-09-09; anything
worth remembering from them is captured here.

## Priority 1: Foundations (do first, they unblock everything below)

1. **Dependency cleanup.** `requirements.txt` is a 2022 pip freeze (Selenium 4.5,
   Pillow 9.2). Local Python is 3.14, CI is 3.10. Move to a short `pyproject.toml`
   with loose pins plus a lockfile, align CI Python with local, and drop anything
   unused. Do this before adding a DB driver or the Places client.
2. **Replace Selenium scraping with the Google Places API.** Returns everything spatula
   scrapes plus city, website, hours, price level, business status, a stable place ID,
   and the canonical Maps URL. Removes Chrome/Selenium/webdriver-manager entirely.
   The place ID becomes the natural primary key for the database.
3. **Write down the review schema once.** The validation rules live as asserts inside
   `build.py` (phone format, bolded dish when taste ≥ 1, uniqueness of name/lat/lon/
   menu/phone/blurb, slug regex). Extract them into one place so the database
   constraints, spatula prompts, and build all share them.
4. **Move reviews into a database.** Starting from scratch (the old `database` branch
   was a SQLite + SQLAlchemy prototype that rewired `build.py` to read from a
   `restaurants` table; it also had a markdown-to-DB migration script, a backup
   script, and `pending/approved/rejected` status). Design principles:
   - `build.py` should keep consuming a plain list of dicts (or a JSON export), so
     templates and derived pages don't change and CI doesn't need DB credentials.
   - Decide photo storage early: git, the GCS bucket, or blobs. The half-finished
     `infra/deploy.sh` dumped images out of Postgres, which is the worst option.
   - New fields to include from the start: `city`, `place_id`, `website`, `hours`.
   - Normalize cuisine and area so a rename doesn't silently change URLs.
   - Rating labels are hardcoded in `build.py`, the templates, and the map legend.
     Define once.
   - Open questions: storage (SQLite in repo vs hosted), how reviews get in (form?
     admin? CLI?), backups.

## Priority 2: Spatula (cheap once Places API is in)

- **`./vilf audit`** that flags permanently closed restaurants via business status.
  Replaces the manual "Remove closed restaurants" commits.
- **Duplicate detection before writing** (place ID or coordinates vs existing).
- **Prompt for cuisine, area, drinks, taste, value, visited** (default today) and
  validate against the schema so a fresh entry is buildable immediately.
- **Accept a photo path or URL** and write `raw/food/<slug>.jpg` in the same run.
- **`check` re-fetches by place ID** instead of searching by name.

## Priority 3: SEO fixes (small, mostly template edits)

- **Fix `addressLocality`**: it currently holds the neighborhood; schema.org means the
  city. Needs the `city` field.
- **Drop fabricated JSON-LD fields**: `paymentAccepted`, `currenciesAccepted`, empty
  `openingHours`, string `acceptsReservations`. Fill from the API or remove.
- **Rethink AggregateRating with ratingCount 1.** Keep the single Review with VILF as
  author; drop the aggregate unless reader ratings arrive.
- **Real `dateModified`** from git history instead of the fixed 2025-02-15 clamp.
- **Add website and hours** to place pages (`sameAs`, `openingHoursSpecification`).
- **Ping Google sitemap and IndexNow on deploy.**

## Priority 4: AI assistant discoverability (build-time additions)

- **Emit `llms.txt` and `llms-full.txt`** from the build. Source is already markdown.
- **Serve each review as markdown** at `/places/<slug>.md` with a
  `<link rel="alternate" type="text/markdown">`.
- **Expose an allowed `/places.json`** (name, cuisine, area, city, ratings, url,
  coords). robots.txt currently disallows `*.geojson`.
- **Plain-text verdict line** at the top of each review ("Taste: Good. Value: Fine.")
  rather than only colored spans.
- **Keep robots.txt open to AI crawlers**; add a comment so a future cleanup doesn't
  block GPTBot / ClaudeBot / PerplexityBot.

## Priority 5: New content surfaces

- **Cuisine-by-neighborhood pages** (e.g. vegan Chinese in Oakland) where there are
  three or more places. This is the query shape people search and ask assistants.
- **Short editorial summary** at the top of each neighborhood and cuisine index page
  so assistants have a quotable answer.

## Housekeeping (do opportunistically)

- **No staging environment.** Merging to `develop` is a production deploy. Fine for
  markdown edits; worth a preview build on PRs once a DB is involved.
- **Mapbox access token is hardcoded in `html/map.html`** and belongs to a
  collaborator's account. Move to your own token or MapLibre's free tiles.
- **`format_cuisine_description` in `build.py`** takes `meta` but reads the outer
  `cuisine` variable. Harmless, but fix when touching that code.
- **Rename or delete `scripts/Untitled.ipynb`**; fold useful cells into real scripts.
- **Defer Google Analytics init until `window.load`** so gtag doesn't block the main
  thread (small change in `html/base.html`).
- **Instagram poster.** Chromedriver / Instagram automation kept breaking. Either move
  to the official Graph API or drop it. Don't revive the Selenium version.
- **Infra refactor from `origin/nix-infra`** (Tristan): move `infra/deploy.sh` into
  `infra/scripts/`, cleaner auth scripts, shellcheck/shfmt pre-commit hooks. Never
  merged.
- **CLAUDE.md** exists; update it when the database structure settles.
