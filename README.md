# Vegans In Love with Food™

Vegan restaurant reviews for the SF Bay Area, published at [vilf.org](https://vilf.org). Reviews live in a database and are edited in a small admin app; publishing renders the whole site as static files into a bucket. The markdown files in `places/` and the photos in `raw/food/` are the pre-database archive: they are imported once by `./vilf db import-markdown` and go away after the cutover (see `infra/README.md`).

## Running locally

Dependencies are managed with [uv](https://docs.astral.sh/uv/). Run everything from the repo root; the `./vilf` wrapper works from any directory.

```bash
uv sync                      # .venv with the pinned Python and packages (add --group instagram for the poster)
./vilf db init               # creates the tables in ./vilf.db (SQLite; see .env.example for Postgres)
./vilf db import-markdown    # one-time seed from places/*.md and raw/food/*.jpg; photos land in ./.media
./vilf serve                 # admin app at http://localhost:8000 (no sign-in locally: you are dev@localhost)
```

To look at the public site instead of the admin, build it and serve the directory:

```bash
./vilf build                 # renders the database into build/ and copies ./.media/img next to it
python3 -m http.server 8080 --directory build
```

Open [`localhost:8080`](http://localhost:8080) (if you open `0.0.0.0:8080` the map will not render). `./vilf build --source files` renders the markdown archive instead of the database; `--source snapshot --snapshot file.json` renders a JSON dump.

```bash
uv run pytest                # the whole suite, offline, a few seconds
```

Copy `.env.example` to `.env` for the Google keys and any non-default storage; every variable is explained there.

## The admin app

`./vilf serve` runs the same FastAPI + htmx app that runs on Cloud Run behind IAP in production.

- **New** looks a restaurant up in Google Places by name and city (or a pasted Google Maps URL), lists the candidates with a flag for ones already reviewed, and prefills the form from the pick. Slugs are derived from the name and never change afterwards.
- **Edit** shows dirty / published / closed chips, a **Preview** of the public page, the form, the photo panel and a "Relink to Google" search. A place that has never been published can be deleted; anything that has been live is marked closed instead (its page stays up with a banner, out of the map and lists).
- **Photo**: upload a JPEG, PNG or HEIC; the original is stored without EXIF and the four site variants (1200x675 and 426x240, JPEG and WebP) are rendered. Tall photos get a crop slider with a live preview.
- **Sync** runs check, audit and enrich against Google over the database and shows when they last ran.
- **Publish** shows what changed since the last snapshot and publishes: validate, snapshot, render, upload changed files, delete stale ones, invalidate the CDN, mark rows published.

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

## Infrastructure

Everything is in the GCP project `vilf-com`: the site bucket behind a load balancer with Cloud CDN, the media bucket served at `vilf.org/img/`, the admin on Cloud Run behind IAP, the database on Neon. `infra/README.md` documents what exists, the setup script (`infra/admin/setup-admin.sh`), CI, backups and the migration runbook. The 2024 Nix/OpenTofu config under `infra/` is frozen; `nix develop` still gives a dev shell with the formatting hooks.

If you edit the bucket by hand, drop the CDN cache:

```bash
gcloud compute url-maps invalidate-cdn-cache vilf-lb --path '/*'
```
