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
