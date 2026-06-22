# MemoGraph production deployment (single-tenant VPS)

This directory contains everything needed to run MemoGraph behind nginx
on a single VPS, with TLS, rate limiting, structured JSON logs,
Prometheus metrics, and a nightly backup sidecar.

If you want multi-tenancy, scale-out, or Kubernetes, this is **not**
the layout for you — those are Phase 3+ deliverables.

## What's here

- `docker-compose.production.yml` — the API container behind an nginx
  reverse proxy plus an optional backup sidecar.
- `nginx.conf` — TLS-terminating proxy, security headers, `/metrics`
  blocked from the public internet.
- `.env.example` — every env var the stack reads, with safe defaults
  and pointers to the relevant phase.
- `tls/` — drop your `fullchain.pem` and `privkey.pem` here (gitignored).
- `backups/` — host-mounted directory the backup sidecar writes into.

## First-time bring-up

```bash
# 1. Configuration
cp deploy/.env.example deploy/.env
${EDITOR:-vi} deploy/.env
# At minimum: set MEMOGRAPH_AUTH_PROVIDER and the matching credentials.

# 2. TLS certificates
mkdir -p deploy/tls
# Either drop in existing certs:
cp /path/to/fullchain.pem deploy/tls/fullchain.pem
cp /path/to/privkey.pem  deploy/tls/privkey.pem
# Or run certbot --nginx-style on the host and point this directory at
# /etc/letsencrypt/live/<domain>/.

# 3. Build and start
docker compose -f deploy/docker-compose.production.yml up -d --build

# 4. Smoke test
curl -fsS https://<your-host>/healthz
# {"status":"alive"}

curl -fsS -H "X-API-Key: <your-key>" https://<your-host>/api/v1/auth/me
# {"id":"apikey:...","scopes":["api_key"]}
```

## Production check-list (before announcing)

- [ ] `MEMOGRAPH_AUTH_PROVIDER` is **not** `none` (the API logs a warning
      at startup if it is).
- [ ] `MEMOGRAPH_DEBUG` is unset (or `0`).
- [ ] TLS certificates installed; `nginx -t` shows no errors inside the
      `nginx` container.
- [ ] Backups landing in `deploy/backups/` after the first 03:17 UTC.
      Verify one manually: `python -m memograph.scripts.run_backup ...`.
- [ ] Prometheus scraper is configured to hit
      `http://<host-only-network>/metrics` — *not* through the public
      nginx, which 404s `/metrics` deliberately.
- [ ] `docker compose ps` shows all containers healthy.
- [ ] Log rotation is working (`docker logs memograph-api | tail` should
      stay bounded; the json-file driver caps at 100 MiB total).

## Operational runbook

### Backup

The backup sidecar runs `memograph.core.backup.create_backup` once a
day at 03:17 UTC and writes archives to `deploy/backups/`. The format
is described in `memograph/core/backup.py`; archives carry a manifest
with per-file sha256, format version, and creation timestamp.

To restore:

```bash
# Stop the API so nothing is writing to the vault.
docker compose -f deploy/docker-compose.production.yml stop memograph

# Verify the backup before extracting.
docker compose -f deploy/docker-compose.production.yml run --rm memograph \
  python -c "from memograph.core.backup import verify_backup; \
print(verify_backup('/backups/<archive>.tar.gz'))"

# Restore into a *fresh* directory; never overwrite the live vault in place.
docker compose -f deploy/docker-compose.production.yml run --rm \
  -v memograph_vault:/data/vault \
  memograph \
  python -c "from memograph.core.backup import restore_backup; \
restore_backup('/backups/<archive>.tar.gz', '/data/vault', overwrite=True)"

docker compose -f deploy/docker-compose.production.yml start memograph
```

### Rotating an API key

```bash
# Generate a new key.
NEW=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
# Append to MEMOGRAPH_API_KEYS in deploy/.env (so old + new both work).
# Reload config without dropping connections:
docker compose -f deploy/docker-compose.production.yml restart memograph
# After clients have migrated, remove the old key from .env and restart again.
```

### Upgrading

```bash
git pull
docker compose -f deploy/docker-compose.production.yml build --no-cache memograph
docker compose -f deploy/docker-compose.production.yml up -d memograph
# nginx config: only restart if you've edited nginx.conf or rotated certs.
docker compose -f deploy/docker-compose.production.yml exec nginx nginx -t
docker compose -f deploy/docker-compose.production.yml exec nginx nginx -s reload
```

## What this stack is *not*

- **Not multi-tenant.** One vault, one set of API keys. Phase 3 of the
  enterprise roadmap addresses tenancy.
- **Not horizontally scaled.** The rate limiter and audit log assume a
  single API process. Switch the rate-limit storage to Redis as a
  prerequisite for scaling out.
- **Not encrypted at rest.** The vault directory is plaintext markdown
  on the host. Use a LUKS-encrypted volume for the host directory if
  the data sensitivity demands it; full at-rest encryption with KMS is
  Phase 5.
- **Not SOC 2 / ISO 27001.** Those are Phase 5 (calendar-bound).
