#!/usr/bin/env bash

if [[ -z $BUCKET || -z $DIRECTORY || -z $URL_MAP ]]; then
    gum log --structured --level error "Arguments not valid" BUCKET "$BUCKET" DIRECTORY "$DIRECTORY" URL_MAP "$URL_MAP"
    exit 1
fi

bucket_object_hashes() {
    gcloud storage objects list "gs://$BUCKET/**" | yq --compact --slurp 'map({(.name): .md5_hash}) | add'
}

old="$(bucket_object_hashes)"
gsutil -m rsync -R "$DIRECTORY" "gs://$BUCKET"
new="$(bucket_object_hashes)"
jq --raw-output --null-input --argjson old "$old" --argjson new "$new" \
    '$old | keys[] | select((in($new) | not) or ($new[.] != $old[.]))' \
    | while read -r key; do
    gcloud compute url-maps invalidate-cdn-cache "$URL_MAP" --async --path "/$key"
done
