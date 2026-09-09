# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

VILF (Vegans In Love with Food) is a static site of vegan restaurant reviews for the SF Bay Area, deployed to https://vilf.org. Content is one markdown file per restaurant in `places/`, with a YAML frontmatter block for metadata and the review body below it. A Python build script renders everything into `build/` via Jinja2 templates. There is no framework, no test suite, and no linter for the Python code.

`IDEAS.md` at the repo root tracks future work. The next planned project is moving reviews out of markdown files into a database, started from scratch (an earlier SQLite prototype was deleted in the September 2026 cleanup).

## Commands

All CLI entry points go through the `./vilf` wrapper, which runs `python3 -m scripts.cli`. Run from the repo root.

```bash
pip install -r requirements.txt          # deps (pinned; Pillow needs libjpeg/zlib on Linux)
./vilf build                             # full site build into build/ (wipes it first)
python3 -m http.server 8080 --directory build   # serve locally; use localhost, not 0.0.0.0, or the map won't render
ls | entr ./vilf build                   # rebuild on change during development

./vilf spatula                           # interactive Google Maps scraper -> new places/<slug>.md
./vilf spatula -s 'Lion Dance Cafe'      # skip the prompt
./vilf spatula --url '<google maps url>' # manual URL mode
./vilf check $(git diff --staged --name-only places/)   # re-scrape staged place files and diff address/lat/lon
```

`spatula` and `check` drive headless Chrome through Selenium and webdriver-manager, so they need Chrome installed and network access. The build itself does not.

Nix users get a dev shell via `nix develop` (direnv picks it up through `.envrc`). Pre-commit hooks there only cover Nix formatting, markdownlint, and lychee link checking, and explicitly exclude `static`, `scripts`, `raw`, `places`, and `html`. The hooks also block direct commits to `develop`.

## Build pipeline (scripts/build.py)

`build_vilf` is one long function. The order matters because later stages consume the `places` list built by the place-page stage:

1. **Images.** Every `raw/food/<slug>.jpg` is resized to 1200x675 and center-cropped (asserts aspect ratio ≤ 16:9), then written as JPEG and WebP to `static/img/food/` plus 426x240 thumbnails to `static/img/thumb/`. Existing outputs are skipped, so `static/img/` (gitignored) acts as a cache. Delete it to force regeneration.
2. **`static/` is copied wholesale to `build/`.**
3. **Place pages.** Each `places/<slug>.md` is split on `---`, frontmatter parsed with PyYAML, body rendered with markdown2. The slug must match `^[0-9a-z-]+$` and is the URL (`/places/<slug>/`). The food image is looked up by slug, so `raw/food/<slug>.jpg` must match the markdown filename. Errors in a single place are caught and printed, not fatal, so watch build output for skipped places.
4. **Derived pages** from the `places` list: `/best/` (sorted taste desc, value desc, slug), `/latest/` (by review age), `/cuisines/` and `/cuisines/<slug>/`, `/neighborhoods/` and `/neighborhoods/<slug>/` (only areas with 3+ places get a page), `places.geojson` for the map, `sitemap.xml`, `robots.txt`.
5. Prints a taste-rating percentage breakdown at the end.

### Place frontmatter

```yaml
name, cuisine, address, area, lat, lon, phone, menu, drinks, visited, taste, value, instagram_published
```

- `taste` and `value` are integers 0–3. Labels: taste = DNR / SGFI / Good / Phenomenal; value = Bad / Fine / Good / Phenomenal. Colors are hardcoded in build.py and mirrored in the templates and map legend.
- `phone` must be `+1` followed by 10 digits or null; the build asserts this.
- `visited` is an ISO date string, quoted.
- If `taste >= 1` the review body must bold at least one dish with `**...**`. The build asserts this, and the bolded dishes feed the meta description and alt text.
- The build asserts `name`, `lat`, `lon`, `menu`, `phone`, and the first 50 words of the review are unique across all places. A copy-pasted review or a duplicate phone number fails the build.
- `area` is free text (neighborhood, not city) and drives the neighborhood pages.

## Templates (html/)

Jinja2, all extending `base.html`, which holds the nav, global CSS, and Google Analytics. `map.html` is the homepage: MapLibre GL loading `/places.geojson`, with a symbol layer for restaurant labels at zoom 14+. `place.html` receives the frontmatter fields plus derived ones (`taste_html`, `value_html`, `drinks_html`, `visited_display`, `phone_display`, `food_image_path`, `alt_text`, `blurb`). Every page embeds JSON-LD structured data, so SEO fields in build.py and templates are coupled.

## Other scripts

- `scripts/spatula.py`: `GoogleMapsScraper` class plus the `scrape_and_gen_md` click command. Writes a frontmatter skeleton with `instagram_published: False`. The filename slug is derived from the restaurant name, with `-N` suffixes on collision.
- `scripts/cross_reference.py`: the `check` command. Re-scrapes each file and compares address and coordinates at 1e-4 resolution.
- `scripts/instagram_poster.py` and `scripts/image_generator.py`: Selenium bot that logs into Instagram using `scripts/credentials.json` (gitignored) and posts reviews with `instagram_published: False`, composing an image from the food photo, logo, and fonts in `scripts/`. Not wired into the CLI; run directly. It has been fragile against Instagram changes.
- `scripts/Untitled.ipynb`: scratch notebook, mostly poster/Instagram experiments.

## Deploy and infra

- GitHub Actions: PRs to `develop` run `./vilf build` as a check. Pushes to `develop` build and `gsutil rsync` the `build/` directory to the `gs://vilf-org` bucket, authenticating with the `VILF_CREDS` secret. So merging to `develop` is a production deploy.
- CDN cache invalidation is manual: `gcloud compute url-maps invalidate-cdn-cache vilf-lb --path /`.
- `infra/` is OpenTofu config generated from Nix (`flake.nix` imports it via the canivete framework): GCP project `vilf-com`, bucket, load balancer, certificate, DNS, and the service account whose key is pushed into the GitHub secret. `infra/deploy.sh` and the commented-out block in `server.nix` are a half-finished design for a server that dumps reviews from a Postgres `submission` table into `places/` and rebuilds. This was never enabled and is the closest prior art for the database migration.
