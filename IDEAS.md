# Ideas

Things to pursue in the future. Cleaned up all old branches on 2026-09-09; anything
worth remembering from them is captured here.

## Now

- **Move reviews into a database.** Starting from scratch (the old `database` branch
  was a SQLite + SQLAlchemy prototype that rewired `build.py` to read from a
  `restaurants` table instead of `places/*.md`; it also had a markdown-to-DB migration
  script, a backup script, and `pending/approved/rejected` review status). Decide
  fresh on: storage (SQLite vs hosted), how reviews get in (form? admin?), how
  `build.py` and `spatula.py` consume it, backups.

## Later

- **Defer Google Analytics init until `window.load`** so gtag doesn't block the main
  thread (small change to the script block in `html/base.html`).
- **Instagram poster reliability.** Chromedriver / Instagram automation kept
  breaking; consider the official Graph API or a simpler manual flow.
- **Infra refactor from `origin/nix-infra`** (Tristan): move `infra/deploy.sh` into
  `infra/scripts/`, cleaner auth scripts, shellcheck/shfmt pre-commit hooks. Never
  merged.
- **Rename `scripts/Untitled.ipynb`** or fold its useful cells into real scripts.
- **CLAUDE.md** for the repo once the database structure settles.

## Spatula

- **Replace Selenium scraping with the Google Places API.** Returns everything spatula
  scrapes plus city, website, hours, price level, business status, a stable place ID,
  and the canonical Maps URL. Removes Chrome/Selenium/webdriver-manager from
  requirements. Do this before or alongside the database work; the place ID is a
  natural primary key.
- **Store the Google place ID in each review** so `check` re-fetches by ID instead of
  searching by name.
- **`./vilf audit` command** that flags permanently closed restaurants via business
  status. Replaces the manual "Remove closed restaurants" commits.
- **Duplicate detection before writing** (place ID or coordinates vs existing files).
- **Prompt for cuisine, area, drinks, taste, value, visited** (default today) and
  validate against build rules so a fresh file is buildable immediately.
- **Accept a photo path or URL** and write `raw/food/<slug>.jpg` in the same run.

## SEO

- **Fix `addressLocality`**: it currently holds the neighborhood; schema.org means the
  city. Add a `city` field (spatula already scrapes it and discards it).
- **Drop fabricated JSON-LD fields**: `paymentAccepted`, `currenciesAccepted`, empty
  `openingHours`, string `acceptsReservations`. Fill from the API or remove.
- **Rethink AggregateRating with ratingCount 1.** Keep the single Review with VILF as
  author; drop the aggregate unless reader ratings arrive.
- **Add website and hours** to place pages once collected (`sameAs`,
  `openingHoursSpecification`).
- **Cuisine-by-neighborhood pages** (e.g. vegan Chinese in Oakland) where there are
  three or more places.
- **Ping Google sitemap and IndexNow on deploy.**
- **Real `dateModified`** from git history instead of the fixed 2025-02-15 clamp in
  `build.py`.

## Discoverability by AI assistants

- **Emit `llms.txt` and `llms-full.txt`** from the build. Source is already markdown.
- **Serve each review as markdown** at `/places/<slug>.md` with a
  `<link rel="alternate" type="text/markdown">`.
- **Expose an allowed `/places.json`** (name, cuisine, area, city, ratings, url,
  coords). robots.txt currently disallows `*.geojson`.
- **Plain-text verdict line** at the top of each review ("Taste: Good. Value: Fine.")
  rather than only colored spans.
- **Keep robots.txt open to AI crawlers**; add a comment so a future cleanup doesn't
  block GPTBot / ClaudeBot / PerplexityBot.
- **Short editorial summary** at the top of each neighborhood and cuisine index page
  so assistants have a quotable answer.
