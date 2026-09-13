# Repository Guidelines

## Project Structure & Module Organization

VILF publishes vegan restaurant reviews as a static site. The database is the source of truth: SQLite locally, Postgres in production.

- `app/`: FastAPI routes, Jinja templates, and htmx admin assets.
- `scripts/`: CLI, database access, validation, Google Places integration, image processing, rendering, and publishing.
- `html/` and `static/`: public-site templates and assets; `build/` is generated output.
- `tests/`: offline pytest suite and recorded fixtures in `tests/fixtures/`.
- `places/` and `raw/food/`: legacy Markdown reviews and photos used for initial import.
- `infra/`: deployment scripts and migration runbook; see `infra/README.md`.

## Build, Test, and Development Commands

Run from the repository root:

- `uv sync --locked`: install dependencies using `uv.lock` and the pinned Python version.
- `./vilf db init`: create database tables.
- `./vilf db import-markdown`: seed an empty database from the legacy archive.
- `./vilf serve --reload`: run the admin at `http://localhost:8000`.
- `./vilf build`: render the database into `build/`, replacing its contents.
- `python3 -m http.server 8080 --directory build`: preview at `http://localhost:8080`.
- `uv run pytest`: run all tests.

After changing `pyproject.toml` dependencies, run `uv lock`.

## Coding Style & Naming Conventions

Follow existing Python style: four-space indentation, snake_case functions/modules, PascalCase classes, and uppercase constants. Add type hints where consistent with surrounding code. Keep shared business logic in `scripts/` for reuse by CLI and routes. Prefix htmx partial templates with `_`, such as `places/_table.html`.

No Python formatter or linter is configured. The Nix development shell supplies formatting hooks, including Markdownlint and Alejandra; do not hand-edit the generated `.pre-commit-config.yaml`.

## Testing Guidelines

Name tests `tests/test_<feature>.py` with `test_*` functions. Use temporary SQLite databases/storage, recorded fixtures, and monkeypatched API calls. Tests must remain offline. Add regression coverage for changed behavior; no numeric coverage threshold is configured. Run focused tests during development and the full suite before submitting; PR CI runs pytest.

## Commit & Pull Request Guidelines

Recent commits use short descriptive subjects, sometimes prefixed by component. Use scoped messages; optional Nix hooks include Commitizen validation. PRs should explain behavior changes, link relevant issues, report validation, and include screenshots for UI changes. PR CI targets `develop`; merging there deploys the admin.

## Configuration & Data Safety

Use `.env.example` for configuration; keep credentials out of Git. Confirm database and storage targets before import or publish. Preserve published reviews by marking them closed; slugs remain immutable. The legacy Nix/OpenTofu infrastructure is frozen: do not run `tofu`.
