# Enterprise installation

This guide walks through deploying MemoGraph for a production
single-tenant or multi-tenant workload. It covers the supported
distribution channels, the runtime configuration needed for a
production deploy, and the post-install validation steps that verify
the deployment is *operationally* healthy — not just running.

If you are evaluating MemoGraph and want to try it out, start with
[QUICK_START.md](QUICK_START.md) instead. This document assumes you
have decided to run MemoGraph yourself.

## Distribution channels

| Channel | Use when |
|---|---|
| Docker image (`ghcr.io/indhar01/memograph:<tag>`) | Default. Most predictable; image is the unit you upgrade. |
| `pip install memograph[web]` | You need to embed MemoGraph into an existing Python service and operate it as a library, not a process. |
| Helm chart (`deploy/helm/memograph/`) | Kubernetes deployment, multi-replica or single-replica. |

The Docker image is built reproducibly; build provenance ships with
the release (see [RELEASE_RUNBOOK.md](RELEASE_RUNBOOK.md) when it
lands in Phase 4.4). Verify the digest you pull matches the digest
the release page advertises.

## Single-tenant deployment

Use this for: a single team, a single customer, or a managed
deployment you operate on their behalf.

### 1. Choose a vault path

The vault is the source of truth — every memory lives there as a
markdown file. Pick a path on a persistent volume:

```bash
export MEMOGRAPH_VAULT=/srv/memograph/vault
mkdir -p "$MEMOGRAPH_VAULT"
chown 1000:1000 "$MEMOGRAPH_VAULT"   # match the container's non-root uid
```

Do **not** point the vault at a network share with relaxed
permissions. The vault contains the full history of every memory the
operator has stored, including any embedded secrets the user pasted
in.

### 2. Configure auth

The default `MEMOGRAPH_AUTH_PROVIDER=none` is unsafe for any
production deploy. Pick one of:

- `api_key` for service-to-service. Generate keys with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`
  and set `MEMOGRAPH_API_KEYS=key1,key2,...`. Keys are stored
  hashed at runtime; the env var is the rotation surface.
- `oidc` for browser flows. See [SSO_SETUP.md](SSO_SETUP.md) for
  the env vars and per-provider notes (Auth0 / WorkOS / Keycloak /
  Azure AD).
- `multi` if you need both — typical for a customer portal that
  also accepts machine credentials.

### 3. Configure CORS

Even with auth enabled, the browser is honest about its origin.
Set the allowlist explicitly:

```bash
export MEMOGRAPH_CORS_ORIGINS=https://memograph.example.com
```

If `MEMOGRAPH_CORS_ORIGINS` is empty and `MEMOGRAPH_DEBUG` is unset,
*all* cross-origin requests are denied. That's the right default for
production. The previous fallback to `localhost:*` only applies when
`MEMOGRAPH_DEBUG=1`.

### 4. Run

The simplest production deployment is the compose file at
`deploy/docker-compose.production.yml`:

```bash
cp deploy/.env.example deploy/.env
$EDITOR deploy/.env             # fill in MEMOGRAPH_API_KEYS, vault path, etc.
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d
```

The compose stack runs:

- the MemoGraph API on `:8000` behind the reverse proxy,
- nginx terminating TLS and forwarding to the API,
- the backup sidecar (see [BACKUP_RESTORE_RUNBOOK.md](BACKUP_RESTORE_RUNBOOK.md)).

### 5. Verify

```bash
curl -fsS https://memograph.example.com/healthz       # liveness
curl -fsS https://memograph.example.com/readyz        # readiness
curl -fsS -H "X-API-Key: $YOUR_KEY" \
  https://memograph.example.com/api/v1/memories
```

Expected:

- `/healthz` returns `200 OK` always (process is up).
- `/readyz` returns `200 OK` only after vault ingestion has
  completed; `503` until then.
- `/api/v1/memories` returns the (empty, on first run) list. A
  `401` here means auth is misconfigured; a `503` means the vault
  has not finished ingesting; a `429` means the rate limiter is
  catching you.

## Multi-tenant deployment

Multi-tenancy is opt-in — set `MEMOGRAPH_TENANCY_ENABLED=1`. The
deployment then needs:

- `MEMOGRAPH_GLOBAL_ROOT` — directory under which each tenant gets
  a subdirectory. This replaces `MEMOGRAPH_VAULT`.
- `MEMOGRAPH_TENANT_MAX_WARM` — LRU cache size for warm kernels.
  Default 64. See the capacity model in
  [adr/0001-tenancy-model.md](adr/0001-tenancy-model.md).
- An auth provider that emits an `admin` scope claim on the JWTs
  (or a dedicated API key with the scope encoded) — only `admin`
  callers can hit `/api/v1/admin/tenants/*`.

Once enabled, tenant lifecycle is managed via the admin API:

```bash
# Create a tenant.
curl -X POST https://memograph.example.com/api/v1/admin/tenants \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "acme"}'

# List tenants.
curl https://memograph.example.com/api/v1/admin/tenants \
  -H "Authorization: Bearer $ADMIN_JWT"

# Hard-delete a tenant. PHASE 3.7 will replace this with a
# scheduled-deletion runbook; today this is destructive and immediate.
curl -X DELETE https://memograph.example.com/api/v1/admin/tenants/acme \
  -H "Authorization: Bearer $ADMIN_JWT"
```

## Required environment variables

| Variable | Required when | Notes |
|---|---|---|
| `MEMOGRAPH_VAULT` | Single-tenant | Path on a persistent volume. |
| `MEMOGRAPH_GLOBAL_ROOT` | Multi-tenant | Replaces `MEMOGRAPH_VAULT`. |
| `MEMOGRAPH_AUTH_PROVIDER` | Always (production) | `none` is dev-only. |
| `MEMOGRAPH_API_KEYS` | `api_key` or `multi` | Comma-separated. |
| `MEMOGRAPH_OIDC_JWKS_URL` | `oidc` or `multi` | From your IdP. |
| `MEMOGRAPH_OIDC_AUDIENCE` | `oidc` or `multi` | Pin tightly; do not accept `*`. |
| `MEMOGRAPH_OIDC_ISSUER` | Recommended | Lets us verify `iss`. |
| `MEMOGRAPH_CORS_ORIGINS` | Browser frontend | Comma-separated allowlist. |
| `MEMOGRAPH_TENANCY_ENABLED` | Multi-tenant | `1` to opt in. |
| `MEMOGRAPH_TENANT_MAX_WARM` | Multi-tenant | LRU size; default 64. |
| `MEMOGRAPH_VAULT_HARD_CAP_BYTES` | Optional | Refuse writes past this size. |
| `MEMOGRAPH_LOG_JSON` | Recommended | `1` for structured logs. |
| `MEMOGRAPH_METRICS_ENABLED` | Recommended | `1` to expose `/metrics`. |
| `MEMOGRAPH_DEBUG` | Never in prod | Echoes exception strings. |

Full env-var inventory and defaults: see
`memograph/web/backend/server.py`. Per-feature deeper dives:

- Auth: [SSO_SETUP.md](SSO_SETUP.md)
- Roles: [RBAC_GUIDE.md](RBAC_GUIDE.md)
- Backups: [BACKUP_RESTORE_RUNBOOK.md](BACKUP_RESTORE_RUNBOOK.md)
- Telemetry: [OBSERVABILITY_GUIDE.md](OBSERVABILITY_GUIDE.md)
- Right-to-erasure: [GDPR_RUNBOOK.md](GDPR_RUNBOOK.md)
- Compliance roadmap: [COMPLIANCE_ROADMAP.md](COMPLIANCE_ROADMAP.md)

## Upgrading

Upgrades are container-replacements: pull the new image tag, restart.
The vault format is forward-compatible within a major version; cache
files carry a `schema_version` and migrate on load (see
[CONCURRENCY.md](CONCURRENCY.md) for the cache invariants).

For multi-version upgrade paths, see `MIGRATION_*.md` guides as they
ship per-version.

## Production checklist

- [ ] `MEMOGRAPH_AUTH_PROVIDER` is not `none`.
- [ ] `MEMOGRAPH_CORS_ORIGINS` is set to a specific allowlist.
- [ ] Reverse proxy terminates TLS; HSTS is on (see
      `deploy/nginx.conf`).
- [ ] Backup sidecar is running and writing to off-host storage.
- [ ] `/metrics` is reachable from the Prometheus scraper but
      blocked from the public internet (see `deploy/nginx.conf`).
- [ ] `MEMOGRAPH_LOG_JSON=1` and logs are shipped to your log
      aggregator with `request_id` indexed.
- [ ] `MEMOGRAPH_DEBUG` is unset.
- [ ] Vault directory is on persistent storage with snapshots
      enabled.
- [ ] Rate-limit defaults match expected traffic; tune via
      `MEMOGRAPH_RATELIMIT_*` if needed.
