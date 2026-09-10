#!/usr/bin/env bash
# Nightly pg_dump of the VILF database, run by launchd (see the plist next to
# this file and infra/README.md). Keeps 30 days of dumps in ~/Backups/vilf.
set -euo pipefail

PG_DUMP=${PG_DUMP:-/opt/homebrew/opt/libpq/bin/pg_dump}
ENV_FILE=$HOME/.config/vilf/backup.env
DEST=$HOME/Backups/vilf
KEEP_DAYS=30

[ -x "$PG_DUMP" ] || { echo "$(date -u +%FT%TZ) error: $PG_DUMP missing (brew install libpq)" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "$(date -u +%FT%TZ) error: $ENV_FILE missing (needs DATABASE_URL=...)" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
[ -n "${DATABASE_URL:-}" ] || { echo "$(date -u +%FT%TZ) error: DATABASE_URL not set in $ENV_FILE" >&2; exit 1; }
# DATABASE_URL is in SQLAlchemy form; libpq does not understand the +psycopg dialect suffix.
URL=${DATABASE_URL/postgresql+psycopg:/postgresql:}

TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$DEST"
OUT=$DEST/vilf-$TS.dump
TMP=$OUT.tmp
trap 'rm -f "$TMP"' EXIT
"$PG_DUMP" --format=custom --no-owner --no-privileges --file="$TMP" "$URL"
mv "$TMP" "$OUT"
PRUNED=$(find "$DEST" -name 'vilf-*.dump' -mtime +"$KEEP_DAYS" -print -delete | wc -l | tr -d ' ')
echo "$(date -u +%FT%TZ) ok $(basename "$OUT") $(wc -c < "$OUT" | tr -d ' ') bytes, pruned $PRUNED"
