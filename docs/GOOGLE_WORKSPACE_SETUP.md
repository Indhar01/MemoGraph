# Google Workspace integration

Two integration points, independent. You can pick either or both.

1. **Identity (auth).** Workspace users sign into MemoGraph with
   their Workspace account. Their Workspace organization id becomes
   their MemoGraph tenant id. **Recommended.**
2. **Drive (portability backup).** A periodic export pushes a
   tarball of the user's vault into a Drive folder they own. They
   can leave at any time with their data; their Workspace also
   serves as a disaster-recovery copy. **Optional but high-value.**

Drive as the *primary* vault store is intentionally **not**
covered here — see [HOSTING_GUIDE.md](HOSTING_GUIDE.md) for why
that path is a trap (latency, quotas, sync semantics) and
[adr/0002-storage-adapter-strategy.md](adr/0002-storage-adapter-strategy.md)
for the architectural decision record.

## 1. Identity — sign in with Google

Google publishes a standard OIDC discovery document and JWKS, so
MemoGraph's existing OIDC adapter handles Workspace with **no new
code**. The full provider-neutral docs are in
[SSO_SETUP.md](SSO_SETUP.md); the Google-specific bits are below.

### Set up an OAuth client in Google Cloud

1. Go to <https://console.cloud.google.com/apis/credentials> in the
   Workspace org's GCP project (create a project if you don't
   have one — billing is not required for the OAuth client).
2. Click **Create Credentials → OAuth client ID**.
3. Application type: **Web application**.
4. Name: `MemoGraph` (anything you want).
5. Authorized redirect URIs: add the URL where your auth gateway
   completes the code exchange. If you front MemoGraph with
   Cloudflare Access (recommended), Cloudflare provides this URL
   on the Access app config page. If you handle the OAuth flow in
   your own frontend, it's whatever your SPA's callback route is.
6. Save. Copy the **Client ID** and **Client secret**.

### Lock the OAuth consent screen to your Workspace

Under **OAuth consent screen** in the same console:

- User type: **Internal** (this restricts sign-in to your
  Workspace; without this, *any* Google account could obtain a
  token).
- App domain: your domain.
- Authorized domains: your domain.
- Scopes requested: `openid`, `email`, `profile`. Add
  `https://www.googleapis.com/auth/drive.file` *only* if you also
  want the Drive backup (section 2 below).

### Wire MemoGraph

```bash
MEMOGRAPH_AUTH_PROVIDER=oidc
MEMOGRAPH_OIDC_JWKS_URL=https://www.googleapis.com/oauth2/v3/certs
MEMOGRAPH_OIDC_ISSUER=https://accounts.google.com
MEMOGRAPH_OIDC_AUDIENCE=<your client id>.apps.googleusercontent.com
```

The audience must exactly match the OAuth client id Google issued
in the previous step. MemoGraph rejects tokens with mismatched
`aud` claims, by design — this is what prevents a token issued
for a different app from being accepted here.

### Tenant mapping

Google ID tokens carry a `hd` claim (hosted-domain) on tokens
issued to Workspace users — for example, `acme.com`. MemoGraph's
auth layer maps `hd` to `User.organization_id` automatically when
tenancy is enabled (`MEMOGRAPH_TENANCY_ENABLED=1`), so each
Workspace becomes its own tenant.

If you run multiple Workspaces against one MemoGraph deployment
(rare; usually you'd run separate deployments), each Workspace
gets its own filesystem-isolated tenant directory under
`MEMOGRAPH_GLOBAL_ROOT/<hd>/`. Cross-tenant isolation is enforced
by the same end-to-end test suite that gates every release
([tests/tenancy/test_isolation_e2e.py](../tests/tenancy/test_isolation_e2e.py)).

### Recommended: front with Cloudflare Access

If you're hosting via [HOSTING_GUIDE.md Option B](HOSTING_GUIDE.md)
(Cloudflare Tunnel), add a Cloudflare Access policy on the same
hostname. Access does the OAuth dance with Google for you and
forwards an authenticated header to MemoGraph. You then accept
the resulting JWT via the same OIDC config.

This gives you **defense in depth**: Cloudflare blocks
unauthenticated traffic at the edge before it ever reaches
MemoGraph, and MemoGraph still validates the token itself rather
than blindly trusting an upstream header.

### Verify before going live

```bash
# Local smoke test against the JWKS endpoint:
curl -fsS https://www.googleapis.com/oauth2/v3/certs | jq '.keys | length'
# Expect: a number >= 1.

# Hit the API with a real Google ID token (grab one from
# https://oauth2.googleapis.com/tokeninfo while testing):
curl -fsS https://memograph.yourdomain.com/api/v1/auth/me \
  -H "Authorization: Bearer $GOOGLE_ID_TOKEN"
# Expect: {"id": "...", "email": "you@yourdomain.com",
#          "organization_id": "yourdomain.com", "scopes": [...]}
```

If `organization_id` is empty in the response, either:

- Your Google account isn't a Workspace member (consumer
  `@gmail.com` accounts don't get `hd`), or
- The OAuth consent screen is set to **External** instead of
  **Internal**, so the token wasn't tagged as a Workspace token.

In multi-tenant mode (`MEMOGRAPH_TENANCY_ENABLED=1`), users
without a tenant claim get **403** by design — see
[memograph/web/backend/tenant_resolver.py](../memograph/web/backend/tenant_resolver.py).

## 2. Drive — portability backup

This section is not yet code-implemented; it's a runbook for the
manual flow that achieves the same outcome. A native MemoGraph
integration is on the roadmap (see
[adr/0002-storage-adapter-strategy.md](adr/0002-storage-adapter-strategy.md));
until then, the cron-based approach below is fully functional.

### Why portability backup is high-value

- **User trust.** "Your memories live in your Workspace; we just
  process them" is a much easier story to sell than "trust us
  with your data".
- **Disaster recovery.** Your VPS can vanish; the user's Drive
  doesn't.
- **Frictionless offboarding.** A user who churns walks away with
  a fully readable copy. No DSR ticket, no export request, no
  legal back-and-forth.
- **Compliance bonus.** GDPR Art. 20 (portability) is satisfied
  out of the box without you doing anything per-request.

### Setup

You need a Google service account with Drive scope, *or* a
per-user OAuth refresh token if you want the backup to land in
each user's personal Drive. The service-account approach is
simpler and recommended unless your trust story specifically
needs per-user Drive ownership.

```bash
# 1. In GCP console, create a service account in the same project
#    as your OIDC OAuth client. Grant it no IAM roles (it doesn't
#    need any GCP permissions).
# 2. Create a JSON key. Download it. Mount it as a secret on your
#    MemoGraph host: /etc/memograph/drive-sa.json.
# 3. In Google Drive, create a folder where backups will land.
#    Share it with the service account's email
#    (looks like memograph-backup@<project>.iam.gserviceaccount.com)
#    with Editor access.
# 4. Note the folder's id (the long string in the share URL).
```

### The backup cron

```bash
#!/bin/sh
# /usr/local/bin/memograph-drive-backup.sh
set -eu

TENANT_ID=${1:-default}
GLOBAL_ROOT=/srv/memograph/tenants
DRIVE_FOLDER_ID=<folder id from step 4>
SA_KEY=/etc/memograph/drive-sa.json
TS=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE=/tmp/${TENANT_ID}-${TS}.tar.gz

# 1. Snapshot the tenant vault into a versioned tarball.
docker exec memograph-api python -m memograph.scripts.run_backup \
  "$GLOBAL_ROOT/$TENANT_ID" "$ARCHIVE"

# 2. Upload to Drive via the official google-drive-uploader image
#    (or rclone, gdrive, or your scripting tool of choice).
docker run --rm \
  -v "$ARCHIVE":"$ARCHIVE":ro \
  -v "$SA_KEY":/sa.json:ro \
  google/cloud-sdk:slim \
  sh -c "gcloud auth activate-service-account --key-file=/sa.json && \
         gcloud storage cp '$ARCHIVE' \
           'gs://drive-bridge/$TENANT_ID/$(basename $ARCHIVE)'"
# (or use the Drive API directly with curl + a generated bearer token —
#  a 30-line shell wrapper does the job.)

rm "$ARCHIVE"
```

Schedule it nightly via cron:

```cron
# /etc/cron.d/memograph-drive-backup
30 2 * * * memograph /usr/local/bin/memograph-drive-backup.sh acme
30 2 * * * memograph /usr/local/bin/memograph-drive-backup.sh globex
```

In multi-tenant deployments, drive a one-line wrapper that loops
over `python -m memograph.scripts.list_tenants` (when that lands)
or simply enumerates the directories under `MEMOGRAPH_GLOBAL_ROOT`.

### Restore from a Drive backup

```bash
# 1. Download the tarball from Drive. (Right-click → Download in
#    the UI, or `gdrive download <file-id>`.)
# 2. Restore via the standard runbook:
docker exec memograph-api python -m memograph.scripts.import_backup \
  /path/to/<tenant>-<ts>.tar.gz
# 3. The vault is restored under the same tenant id as it was
#    backed up under. Verify:
curl -fsS https://memograph.yourdomain.com/api/v1/admin/tenants \
  -H "Authorization: Bearer $ADMIN_JWT" | jq
```

The end-to-end procedure is documented in
[BACKUP_RESTORE_RUNBOOK.md](BACKUP_RESTORE_RUNBOOK.md).

## 3. Future work — first-class Drive integration

A native `memograph drive sync` subcommand and a `GoogleDriveBackend`
storage adapter are tracked in
[adr/0002-storage-adapter-strategy.md](adr/0002-storage-adapter-strategy.md).
Until that lands, the cron + service-account flow above is the
supported path.

If you want this earlier, the integration is small (the existing
[memograph/integrations/obsidian.py](../memograph/integrations/obsidian.py)
two-way sync code is a structural template; Drive substitutes
for the local filesystem watcher with the Drive Changes API).
File a tracking issue and we'll prioritise it.

## Where to go next

- **[HOSTING_GUIDE.md](HOSTING_GUIDE.md)** — pick a compute path
  that pairs with this Workspace setup.
- **[SSO_SETUP.md](SSO_SETUP.md)** — provider-neutral details on
  the OIDC + JWKS flow.
- **[GDPR_RUNBOOK.md](GDPR_RUNBOOK.md)** — once Workspace identity
  is in place, scheduled deletion automatically maps onto
  Workspace org boundaries.
