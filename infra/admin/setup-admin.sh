#!/usr/bin/env bash
# One-off cloud setup for the VILF admin app (Cloud Run behind IAP, media bucket
# on the CDN, deployer for GitHub Actions). Run sections individually:
#
#   ./infra/admin/setup-admin.sh <section>
#
# See infra/README.md for the order to run them in during the migration.
# Every section prints what it is about to do and is safe to re-run: creates
# are guarded by a describe check, IAM bindings are idempotent.
set -euo pipefail
cd "$(dirname "$0")/../.."

PROJECT=vilf-com
PN=952410211826
REGION=us-west1
OWNER=itsi@vilf.org
SERVICE=vilf-admin
MEDIA_BUCKET=vilf-media
SITE_BUCKET=vilf-org
URL_MAP=vilf-lb
REPO=vilf
RUNTIME_SA=vilf-admin@$PROJECT.iam.gserviceaccount.com
DEPLOY_SA=vilf-deployer@$PROJECT.iam.gserviceaccount.com
IAP_AGENT=service-$PN@gcp-sa-iap.iam.gserviceaccount.com
GH_REPO=ItsiW/VILF
SECRETS="vilf-database-url vilf-google-places-api-key vilf-maps-embed-api-key"
URLMAP_BACKUP=infra/admin/urlmap-before.yaml

export CLOUDSDK_CORE_PROJECT=$PROJECT

say() { printf '\n==> %s\n' "$*"; }

apis() {
    say "apis: enabling run, artifactregistry, secretmanager, iap"
    gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
        secretmanager.googleapis.com iap.googleapis.com
}

buckets() {
    say "buckets: creating gs://$MEDIA_BUCKET ($REGION, uniform access, 30d soft delete, public read)"
    if ! gcloud storage buckets describe "gs://$MEDIA_BUCKET" >/dev/null 2>&1; then
        gcloud storage buckets create "gs://$MEDIA_BUCKET" --location="$REGION" \
            --uniform-bucket-level-access --soft-delete-duration=30d
    fi
    gcloud storage buckets add-iam-policy-binding "gs://$MEDIA_BUCKET" \
        --member=allUsers --role=roles/storage.objectViewer
    say "buckets: bumping gs://$SITE_BUCKET soft delete to 30d"
    gcloud storage buckets update "gs://$SITE_BUCKET" --soft-delete-duration=30d
    # Seed the media bucket from the current site once, before the url map cutover:
    # gcloud storage rsync -r gs://vilf-org/img gs://vilf-media/img
    # gcloud storage objects update 'gs://vilf-media/img/**' --cache-control='public, max-age=86400'
}

cdn() {
    say "cdn: creating backend bucket $MEDIA_BUCKET with CDN on"
    if ! gcloud compute backend-buckets describe "$MEDIA_BUCKET" >/dev/null 2>&1; then
        gcloud compute backend-buckets create "$MEDIA_BUCKET" --gcs-bucket-name="$MEDIA_BUCKET" \
            --enable-cdn --cache-mode=CACHE_ALL_STATIC --default-ttl=86400 --max-ttl=604800 \
            --custom-response-header='X-Vilf-Backend: media'
    fi
}

service-accounts() {
    say "service-accounts: creating runtime SA $RUNTIME_SA"
    if ! gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1; then
        gcloud iam service-accounts create vilf-admin --display-name='VILF admin runtime'
    fi
}

roles() {
    say "roles: objectAdmin for $RUNTIME_SA on gs://$SITE_BUCKET and gs://$MEDIA_BUCKET"
    for b in "$SITE_BUCKET" "$MEDIA_BUCKET"; do
        gcloud storage buckets add-iam-policy-binding "gs://$b" \
            --member="serviceAccount:$RUNTIME_SA" --role=roles/storage.objectAdmin
    done
    say "roles: custom role vilfCdnInvalidator bound to $RUNTIME_SA"
    if ! gcloud iam roles describe vilfCdnInvalidator --project="$PROJECT" >/dev/null 2>&1; then
        # globalOperations.get: gcloud and the compute client poll the invalidation operation
        gcloud iam roles create vilfCdnInvalidator --project="$PROJECT" \
            --title='VILF CDN invalidator' --stage=GA \
            --permissions=compute.urlMaps.invalidateCache,compute.globalOperations.get
    fi
    gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$RUNTIME_SA" \
        --role="projects/$PROJECT/roles/vilfCdnInvalidator" --condition=None >/dev/null
}

registry() {
    say "registry: Artifact Registry repo $REPO (docker, $REGION) with cleanup policy"
    if ! gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1; then
        gcloud artifacts repositories create "$REPO" --repository-format=docker \
            --location="$REGION" --description='VILF admin images'
    fi
    gcloud artifacts repositories set-cleanup-policies "$REPO" --location="$REGION" \
        --policy=infra/admin/ar-cleanup.json --no-dry-run
}

secrets() {
    say "secrets: creating empty secrets and granting $RUNTIME_SA access"
    for name in $SECRETS; do
        if ! gcloud secrets describe "$name" >/dev/null 2>&1; then
            gcloud secrets create "$name" --replication-policy=automatic
        fi
        gcloud secrets add-iam-policy-binding "$name" \
            --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor >/dev/null
    done
    cat <<MSG

Secrets exist but have no versions. Add one per secret by hand:

    printf %s "\$VALUE" | gcloud secrets versions add vilf-database-url --data-file=-
    printf %s "\$VALUE" | gcloud secrets versions add vilf-google-places-api-key --data-file=-
    printf %s "\$VALUE" | gcloud secrets versions add vilf-maps-embed-api-key --data-file=-

vilf-database-url is the SQLAlchemy form: postgresql+psycopg://USER:PASSWORD@HOST/DB
MSG
}

run() {
    # A deployer with only run.developer + serviceAccountUser on vilf-admin cannot
    # CREATE a service (the create path needs actAs on the default compute SA), so
    # the service is bootstrapped here with Google's hello image and CI only ever
    # updates the image afterwards. --set-secrets fails until every secret has a version.
    if ! gcloud run services describe "$SERVICE" --region="$REGION" >/dev/null 2>&1; then
        say "run: bootstrapping Cloud Run service $SERVICE with the hello image"
        gcloud run deploy "$SERVICE" --region="$REGION" \
            --image=us-docker.pkg.dev/cloudrun/container/hello \
            --no-allow-unauthenticated --service-account="$RUNTIME_SA" --quiet
    fi
    say "run: updating $SERVICE scaling, secrets and env (image is left to CI)"
    gcloud run services update "$SERVICE" --region="$REGION" \
        --min-instances=0 --max-instances=1 --cpu=1 --memory=1Gi --concurrency=10 \
        --timeout=900 --cpu-boost --service-account="$RUNTIME_SA" \
        --set-secrets=DATABASE_URL=vilf-database-url:latest,GOOGLE_PLACES_API_KEY=vilf-google-places-api-key:latest,GOOGLE_MAPS_EMBED_API_KEY=vilf-maps-embed-api-key:latest \
        --set-env-vars=VILF_SITE_STORAGE=gs://$SITE_BUCKET,VILF_MEDIA_STORAGE=gs://$MEDIA_BUCKET,VILF_BACKUP_STORAGE=gs://vilf-backups,VILF_URL_MAP=$URL_MAP,VILF_SITE_URL=https://vilf.org,GOOGLE_CLOUD_PROJECT=$PROJECT,VILF_ADMIN_EMAIL=$OWNER,VILF_INDEXNOW=1
}

iap() {
    say "iap: IAP service agent needs run.invoker to forward traffic to $SERVICE"
    gcloud beta services identity create --service=iap.googleapis.com || true
    gcloud run services add-iam-policy-binding "$SERVICE" --region="$REGION" \
        --member="serviceAccount:$IAP_AGENT" --role=roles/run.invoker >/dev/null
    say "iap: enabling IAP on $SERVICE and allowing $OWNER"
    # (the service was deployed with --no-allow-unauthenticated; `update` has no such flag)
    gcloud run services update "$SERVICE" --region="$REGION" --iap
    gcloud iap web add-iam-policy-binding --resource-type=cloud-run --region="$REGION" \
        --service="$SERVICE" --member="user:$OWNER" --role=roles/iap.httpsResourceAccessor >/dev/null
    printf '\nAdmin URL: %s\n' "$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
}

deployer() {
    say "deployer: creating $DEPLOY_SA with run.developer, artifactregistry.writer on $REPO, serviceAccountUser on $RUNTIME_SA"
    if ! gcloud iam service-accounts describe "$DEPLOY_SA" >/dev/null 2>&1; then
        gcloud iam service-accounts create vilf-deployer --display-name='VILF GitHub Actions deployer'
    fi
    gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEPLOY_SA" \
        --role=roles/run.developer --condition=None >/dev/null
    gcloud artifacts repositories add-iam-policy-binding "$REPO" --location="$REGION" \
        --member="serviceAccount:$DEPLOY_SA" --role=roles/artifactregistry.writer >/dev/null
    gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
        --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser >/dev/null
    say "deployer: creating a key and storing it as GitHub secret VILF_DEPLOY_KEY on $GH_REPO"
    # Not `local`: the EXIT trap runs after this function returns, and under
    # `set -u` a vanished local would abort the script with "key: unbound".
    key=$(mktemp)
    trap 'rm -f "${key:-}"' EXIT
    gcloud iam service-accounts keys create "$key" --iam-account="$DEPLOY_SA"
    gh secret set VILF_DEPLOY_KEY --repo "$GH_REPO" < "$key"
    shred -u "$key" 2>/dev/null || rm -f "$key"
    cat <<MSG

Key stored. After the cutover, retire the old deployer:
    gh secret delete VILF_CREDS --repo $GH_REPO
    gcloud iam service-accounts delete vilfer@$PROJECT.iam.gserviceaccount.com
Old keys of $DEPLOY_SA (when rotating):
    gcloud iam service-accounts keys list --iam-account=$DEPLOY_SA --managed-by=user
MSG
}

urlmap() {
    # Run LAST, during the cutover, after gs://vilf-media is seeded.
    if [ -e "$URLMAP_BACKUP" ] && [ "${FORCE:-0}" != 1 ]; then
        echo "$URLMAP_BACKUP already exists (the rollback record); set FORCE=1 to overwrite it" >&2
        exit 1
    fi
    say "urlmap: exporting $URL_MAP to $URLMAP_BACKUP"
    gcloud compute url-maps export "$URL_MAP" --global --destination="$URLMAP_BACKUP"
    say "urlmap: routing /img/* on $URL_MAP to backend bucket $MEDIA_BUCKET"
    gcloud compute url-maps add-path-matcher "$URL_MAP" --global --path-matcher-name=media \
        --default-backend-bucket="$SITE_BUCKET" --backend-bucket-path-rules="/img/*=$MEDIA_BUCKET" \
        --new-hosts='*'
    cat <<MSG

Verify (the media backend adds X-Vilf-Backend: media; propagation takes a few minutes):
    curl -sI https://vilf.org/img/food/<slug>.jpg | grep -i -e HTTP -e x-vilf-backend
    curl -sI https://vilf.org/ | grep HTTP
Then drop the CDN cache:
    gcloud compute url-maps invalidate-cdn-cache $URL_MAP --path '/*'
Rollback:
    gcloud compute url-maps remove-path-matcher $URL_MAP --global --path-matcher-name=media
Full rollback to the exported map:
    gcloud compute url-maps import $URL_MAP --global --source=$URLMAP_BACKUP
MSG
}

all-but-urlmap() {
    apis; buckets; cdn; service-accounts; roles; registry; secrets; deployer
    cat <<MSG

Done up to the secrets. Next: add a version to each secret (see above), then
    ./infra/admin/setup-admin.sh run
    ./infra/admin/setup-admin.sh iap
then merge to develop so CI deploys the real image, seed the media bucket, and
finally run the urlmap section during the cutover.
MSG
}

usage() {
    cat >&2 <<MSG
usage: $0 <section>
sections: apis buckets cdn service-accounts roles registry secrets run iap deployer urlmap all-but-urlmap
MSG
    exit 2
}

case "${1:-}" in
    apis|buckets|cdn|service-accounts|roles|registry|secrets|run|iap|deployer|urlmap|all-but-urlmap) "$1" ;;
    *) usage ;;
esac
