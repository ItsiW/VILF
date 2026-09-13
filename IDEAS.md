# Ideas

The database migration and practical tooling follow-ups are complete. Maintenance
history lives in the admin's Sync page and the `runs` table; infrastructure and
recovery instructions are in `infra/README.md` and `infra/backup/README.md`.

## Completed tooling cleanup

- Explicit `unlinked` preference for entries intentionally absent from Google Maps.
- Review validation before Google checks, streaming CLI audit output, and Google
  Maps short-link support shared by the CLI and admin.
- Coordinates rounded to seven decimal places on save, avoiding floating-point
  noise without a SQL type migration.
- Clear partial-publish failure messages and deletion checks before uploads.
  The existing `max(25, 20%)` deletion threshold remains appropriate at this size.
- Removed the Markdown importer and `--source files`; JSON backup restore remains.
- Ruff correctness linting in CI, shared render-test fixtures, explicit Linux/AMD64
  container builds, and grouped weekly Dependabot PRs (reviewed before merging).
- Homepage migrated from collaborator-owned Mapbox to OpenFreeMap + MapLibre;
  retain provider attribution.

## Deliberate decisions

- Local admin uses production data. No hosted staging or separate preview workflow.
- Keep Git history intact, including historical photos; no history rewrite.
- No visitor accounts, comments, favourites, or other visitor-facing additions.
- No multi-user roles, row edit-history system, or draft-photo system for now.
  Photo changes reach the public media bucket immediately; page edits wait for Publish.
- Never upload database backups to the public media bucket. Cloud and Mac backups
  already cover restaurant data and original photos.

## Deferred: Instagram

The poster still uses Selenium and expects legacy Markdown input. Leave it alone
until deciding whether to adapt it to the database/official API or remove it.
Its fonts and PNG assets in `scripts/` are also deliberately unchanged.
