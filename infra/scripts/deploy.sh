#! /usr/bin/env bash

tmp=$(mktemp -d)

# Clone repo and install requirements in virtualenv
venv="$tmp/venv"
repo="$tmp/repo"
python -m venv "$venv"
git clone --depth 1 --branch "$VILF_GIT_BRANCH" "$VILF_GIT_URL" "$repo"
"$venv/bin/pip" install --requirement "$repo/requirements.txt"

# Dump table as JSON entries
json="$tmp/$VILF_PG_TABLE.json"
psql \
    --username "$VILF_PG_USER" \
    --host "$VILF_PG_HOST" \
    --dbname "$VILF_PG_DB" \
    --no-password \
    --command "SELECT array_to_json(array_agg(row_to_json(t))) FROM (SELECT contents, image, name FROM $VILF_PG_TABLE) t;" \
    --tuples-only \
    --output "$json"

# Generate markdown and image files from each entry
bash <(jq --raw-output '.[] | "echo \(.contents | @sh) > \"$repo/places/\(.name | @sh).md\""' "$json")
bash <(jq --raw-output '.[] | "echo \(.image | @sh) > \"$repo/raw/food/\(.name | @sh)\""' "$json")

# Build and publish project
"$venv/bin/python" "$repo/vilf" build
gsutil -m rsync -R "$repo/build" "$VILF_GCS_BUCKET"
