# Admin custom domain

`https://admin.vilf.org` uses the existing `vilf-lb` load balancer at
`34.160.8.176`. It does not use Cloud Run's preview domain-mapping feature.

## Resources

- Cloud DNS zone `vilf-org`: `admin.vilf.org` A record and
  `_acme-challenge.admin.vilf.org` CNAME for certificate renewal.
- Certificate Manager DNS authorization and certificate: `admin-vilf-org`.
- Existing certificate map `vilf-map`: exact-host entry `admin-vilf-org`.
  The primary `vilf-org` certificate entry is unchanged.
- Regional serverless NEG `vilf-admin-neg` (`us-west1`) targets Cloud Run
  service `vilf-admin`.
- Global backend service `vilf-admin-backend`: `EXTERNAL`, HTTP, CDN disabled.
- URL map `vilf-lb`: host `admin.vilf.org` selects path matcher `vilf-admin`,
  whose default is the admin backend. The map's public-site default remains
  backend bucket `vilf-org`.
- Existing HTTP frontend redirects to HTTPS while preserving the hostname.

IAP stays enabled **directly on Cloud Run**, protecting both the custom hostname
and `run.app`. Do not also enable IAP on the backend service, enable CDN for the
admin, or grant unauthenticated Cloud Run invocation. The browser Maps Embed API
key allows `https://admin.vilf.org/*` alongside its existing referrers.

## Verification

```bash
dig +short admin.vilf.org
curl -sI https://admin.vilf.org/
curl -sI http://admin.vilf.org/
curl -sI https://vilf.org/
gcloud certificate-manager certificates describe admin-vilf-org \
  --location=global --project=vilf-com --format='value(managed.state)'
gcloud compute url-maps describe vilf-lb --global --project=vilf-com
```

Expect a valid certificate, a Google sign-in redirect for unauthenticated HTTPS
requests, an HTTP-to-HTTPS redirect, and the public site still returning normally.
Sign in as `itsi@vilf.org` and check Places, the map preview, and Backups.

The later media cutover may add a wildcard host matcher for `/img/*`; the exact
`admin.vilf.org` matcher must be preserved and takes precedence over that wildcard.
Do not import an old full URL map that predates the admin hostname.

## Rollback

The original `https://vilf-admin-952410211826.us-west1.run.app/` remains available.
For an admin-domain rollback, remove only the `admin.vilf.org` A record, then the
`vilf-admin` path matcher and its host rule after confirming their exact targets.
Do not replace the entire URL map or alter the public site's certificate entry.
Keep the certificate-authorization CNAME if the hostname will be restored later.

The legacy OpenTofu configuration is frozen; these resources are managed through
GCP directly. Do not run `tofu` to reconcile them.

References: [Cloud Run custom domains](https://docs.cloud.google.com/run/docs/mapping-custom-domains)
and [direct IAP protection](https://docs.cloud.google.com/iap/docs/enabling-cloud-run).
