# MemoGraph production deployment

This directory carries three deployment options. Pick the one that
matches the cluster you already operate; they're maintained side-by-side
so you don't have to translate from one to another.

| Layout | Best for | Multi-tenant | Scale-out |
| --- | --- | --- | --- |
| `docker-compose.production.yml` + `nginx.conf` | Single VPS, one operator, fastest bring-up | ✅ (opt-in) | ❌ |
| `helm/memograph/` | Existing Kubernetes cluster, Helm-shop | ✅ | ✅ (after Redis) |
| `k8s/` (raw + Kustomize) | Kubernetes without Helm, GitOps via Flux/ArgoCD | ✅ | ✅ (after Redis) |

The Docker Compose stack and the K8s manifests both consume the same
container image: `ghcr.io/indhar01/memograph:<tag>` (published by
`.github/workflows/release.yml` on every `v*.*.*` tag, multi-arch,
cosign-signed). Pull a specific digest in production rather than a
floating tag.

## What's in each layout

### `helm/memograph/` (recommended for Kubernetes)

```bash
# Default: single-tenant, API-key auth, ClusterIP service.
helm install memograph deploy/helm/memograph \
  --namespace memograph --create-namespace \
  --set-file auth.apiKey.keys=./keys.txt

# Multi-tenant with OIDC, exposed via Ingress + cert-manager:
helm install memograph deploy/helm/memograph \
  --namespace memograph --create-namespace \
  --set memograph.tenancyEnabled=true \
  --set auth.provider=oidc \
  --set auth.oidc.jwksUrl=https://example.auth0.com/.well-known/jwks.json \
  --set auth.oidc.issuer=https://example.auth0.com/ \
  --set auth.oidc.audience=memograph-api \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=memograph.example.com \
  --set ingress.hosts[0].paths[0].path=/ \
  --set ingress.hosts[0].paths[0].pathType=Prefix
```

Every supported knob lives in `helm/memograph/values.yaml` with inline
comments. Keys not in that file aren't promised between chart versions.

### `k8s/` (raw manifests + Kustomize)

```bash
# Edit the placeholders first — secret.yaml has REPLACE_ME, ingress.yaml
# has memograph.example.com, deployment.yaml has the image tag.
kubectl apply -k deploy/k8s/
```

For GitOps, point Flux/ArgoCD at this directory and overlay env-specific
patches under `deploy/k8s/overlays/<env>/`.

### `docker-compose.production.yml` + `nginx.conf` (single VPS)

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

## Image provenance

Every `v*.*.*` git tag triggers `.github/workflows/release.yml`, which:

1. Builds multi-arch (`linux/amd64`, `linux/arm64`) and pushes to
   `ghcr.io/indhar01/memograph` with tags `vX.Y.Z`, `X.Y`, `X`, and
   `latest` (the last only on stable, non-prerelease tags).
2. Signs each tag's digest with **cosign keyless** — the signature is
   anchored to the GitHub Actions OIDC identity of the run.
3. Emits a **CycloneDX SBOM** as a workflow artifact and a SLSA-v1
   build-provenance attestation on the image manifest.

Verify before deploying:

```bash
# Pin the digest in your manifests/values once verified.
cosign verify \
  --certificate-identity-regexp 'https://github.com/Indhar01/MemoGraph/\.github/workflows/release\.yml.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/indhar01/memograph:v0.3.0
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
