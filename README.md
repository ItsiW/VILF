# Vegans In Love with Food™

Vegan restaurant reviews for the SF Bay Area, published at [vilf.org](https://vilf.org). Reviews live in a database and are edited in the admin app; publishing renders the site as static files into a bucket. Original photos and generated variants live in `gs://vilf-media`. The legacy `places/` and `raw/food/` files have been removed from the checkout; Git history retains them. See `infra/backup/README.md` for current backups and recovery.

## Running locally

Dependencies are managed with [uv](https://docs.astral.sh/uv/). Run everything from the repo root; the `./vilf` wrapper works from any directory.

```bash
uv sync                      # .venv with the pinned Python and packages (add --group instagram for the poster)
./vilf db init               # only for a new, isolated database; confirm DATABASE_URL first
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

To look at the public site instead of the admin, build it and serve the directory:

```bash
./vilf build                 # renders the database into build/ and copies ./.media/img next to it
python3 -m http.server 8080 --directory build
```

Open [`localhost:8080`](http://localhost:8080) (if you open `0.0.0.0:8080` the map will not render). `./vilf build --source snapshot --snapshot file.json` renders a JSON dump. The old file-based build and Markdown importer have been removed; use current JSON backups for recovery.

The owner's local `.env` connects to the same production database and buckets as the hosted admin: local edits and publishing affect the live site. For isolated development, configure separate SQLite/local storage targets before initializing or restoring. Seed an isolated database from a current JSON backup using `./vilf db restore-snapshot /path/to/backup.json`; this replaces its restaurant rows. Photos are restored separately (see the backup runbook).

```bash
uv run ruff check .          # lightweight correctness linting
uv run pytest                # the whole suite, offline, a few seconds
```

Copy `.env.example` to `.env` for the Google keys and any non-default storage; every variable is explained there.

## The admin app

`./vilf serve` runs the same FastAPI + htmx app that runs on Cloud Run behind IAP in production.

- **New** looks a restaurant up in Google Places by name and city (or a pasted Google Maps URL, including `maps.app.goo.gl` short links), lists the candidates with a flag for ones already reviewed, and prefills the form from the pick. Slugs are derived from the name and never change afterwards.
- **Edit** shows dirty / published / closed chips, a **Preview** of the public page, the form, the photo panel and a "Relink to Google" search. A place that has never been published can be deleted; anything that has been live is marked closed instead (its page stays up with a banner, out of the map and lists).
- **Photo**: upload a JPEG, PNG or HEIC; the original is stored without EXIF and the four site variants (1200x675 and 426x240, JPEG and WebP) are rendered. Tall photos get a crop slider with a live preview.
- **Sync** checks saved reviews before calling Google and shows audit history. Places intentionally absent from Google Maps can be marked as such on their edit form; check/audit/enrich skip those entries. CLI audit prints problems as they arrive.
- **Publish** shows what changed since the last snapshot and publishes: validate, snapshot, render, upload changed files, delete stale ones, invalidate the CDN, mark rows published. The mass-delete guard runs before uploads; a partial-failure message explains when retrying is needed.

### CLI equivalents

Every admin action has a command, all reading `.env`:

```bash
./vilf spatula -s 'Lion Dance Cafe Oakland'         # create a row from a Google lookup (prompts for ratings)
./vilf spatula --place-id ChIJ... --photo ~/food.jpg  # skip the search; store the photo too
./vilf check [SLUGS] --contact --fix                # compare address/coords/phone/website with Google, write fixes
./vilf audit [SLUGS] --mark-closed                  # flag places Google lists as permanently closed
./vilf enrich [SLUGS] --dry-run                     # link rows without a place_id, fill city
./vilf publish [--force]                            # render and mirror into the site storage (this is the deploy)
./vilf db snapshot backup.json                      # dump every row; restore with db restore-snapshot backup.json [--publish]
```

`spatula`, `check`, `audit` and `enrich` need `GOOGLE_PLACES_API_KEY`; `./vilf --help` and each subcommand's `--help` list every flag.

Coordinates are rounded to seven decimal places when saved (roughly centimetre precision). GitHub CI runs lint and tests; Dependabot opens grouped weekly dependency-update PRs for review, not automatic deployment. Build containers with `docker build --platform linux/amd64 -t vilf-admin .` on a Mac.

## Infrastructure

The public homepage map uses [OpenFreeMap Liberty](https://openfreemap.org/quick_start/)
with MapLibre GL JS 6.9.0 (pinned JS module/CSS URLs in `html/map.html`). No account,
API key, or billing setup is required. OpenFreeMap's public service has no uptime
guarantee; keep its automatic OpenStreetMap/OpenMapTiles attribution visible.
Restaurant markers still come from our generated `places.geojson`. This does not
change the Google Places lookup or Google Maps embeds in the admin.

Everything is in the GCP project `vilf-com`: the site bucket behind a load balancer with Cloud CDN, the media bucket served at `vilf.org/img/`, the admin on Cloud Run behind IAP, the database on Neon. `infra/README.md` documents what exists, the setup script (`infra/admin/setup-admin.sh`), CI, backups and the migration runbook. Development uses `uv`; the unused Nix/OpenTofu setup has been removed without changing live cloud resources.

If you edit the bucket by hand, drop the CDN cache:

```bash
gcloud compute url-maps invalidate-cdn-cache vilf-lb --path '/*'
```
