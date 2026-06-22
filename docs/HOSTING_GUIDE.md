# Hosting MemoGraph for free

This guide covers four genuinely-no-cost paths to run MemoGraph in
production, ranked by how well they match the product's actual
shape (a vault of files on disk + a long-running FastAPI process).

If you only read one section, read **Option B** — for most users
with any spare hardware, Cloudflare Tunnel + Docker Compose is the
fastest, most sovereign, and cheapest answer.

## TL;DR

| Option | Where compute runs | Where vault lives | Cost | Best when |
|---|---|---|---|---|
| **A.** Oracle Cloud Free Tier | Oracle ARM VPS | VPS disk | $0 forever | You want a real cloud server with a DNS A record |
| **B.** Cloudflare Tunnel + your hardware | Your laptop / NAS / Pi | Local disk | $0 forever | You have any always-on box; want sovereignty + speed |
| **C.** GCP always-free stitch | Cloud Run | GCS Fuse | $0 within free tier | You're already on GCP and accept cold-start latency |
| **D.** GitHub repo as vault | Anywhere (incl. A or B) | Private GitHub repo | $0 within GitHub free | You want git's history/diff/PR semantics on memories |

All four work with **Google Workspace as identity** via the OIDC
adapter that ships in [memograph/web/backend/auth.py](../memograph/web/backend/auth.py).
See [GOOGLE_WORKSPACE_SETUP.md](GOOGLE_WORKSPACE_SETUP.md).

## Option A — Oracle Cloud Free Tier (real VPS)

The most "normal" answer. A regular Linux VPS, persistent disk, public
IP, no scale-to-zero gotchas. Genuinely free in perpetuity for the
shapes Oracle calls "Always Free Eligible".

### What you get

- 4 ARM cores (Ampere A1) and 24 GB RAM, or 2 AMD VMs with 1 GB RAM each
- 200 GB total block storage
- 10 TB/month outbound bandwidth
- A public IPv4 address

### Setup

```bash
# 1. Create the VM in the Oracle Cloud console; pick "Always Free
#    Eligible" shape (Ampere A1 with 4 OCPU / 24 GB recommended).
# 2. SSH in. Install Docker.
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker

# 3. Clone MemoGraph and start.
git clone https://github.com/Indhar01/MemoGraph.git
cd MemoGraph
cp .env.example .env  # edit auth + vault path
docker compose up -d

# 4. Open ingress on Oracle's network ACL for 80/443. Point a DNS
#    A record at the VM's public IP. Front with caddy or nginx for
#    TLS (Let's Encrypt is free).
```

### Pitfalls

- **Region availability.** ARM A1 instances are reclaimed when Oracle
  is short on capacity. Try multiple regions during creation; once
  yours is up, it's yours.
- **Idle reclamation.** Oracle reclaims VMs that have been idle for
  a long stretch. Add a cron that hits `/healthz` every hour to
  keep the VM "warm" by their definition.
- **No SLA.** Free tier comes with no uptime guarantee. Fine for
  personal use; use Option B if you want hardware you control.

## Option B — Cloudflare Tunnel + your hardware (recommended)

The cleanest "free forever" answer because it removes the cloud
provider entirely. Your laptop, an old desktop, a NAS, or a $35
Raspberry Pi runs MemoGraph; Cloudflare Tunnel exposes it at
`memograph.yourdomain.com` over HTTPS without port forwarding, a
static IP, or an inbound firewall hole.

### Why this beats Option A for most users

- **Free, no card-on-file required.** Cloudflare Tunnel is free.
- **Faster than any free cloud.** Local NVMe outruns Oracle's free-tier
  block storage by 10-100x on the read paths MemoGraph hits during
  retrieval. Latency from your client over Cloudflare's edge is
  often ~30 ms.
- **Data sovereignty.** Your memories never leave hardware you own.
  Compliance becomes much simpler.
- **Survives ISP changes.** Tunnel reconnects automatically; no DNS
  re-pointing when your home IP rotates.

### Setup

```bash
# 1. Install Docker on whatever box you have (Linux preferred;
#    Windows/macOS work via Docker Desktop). Start MemoGraph:
docker compose up -d

# 2. Sign up for a free Cloudflare account; add a domain (free if
#    you already own one, or buy one for $9/yr).
# 3. In the Cloudflare Zero Trust dashboard, create a Tunnel.
# 4. Run the cloudflared connector on the same box:
cloudflared tunnel run --token <token>

# 5. Add a public hostname under the tunnel:
#    Subdomain: memograph
#    Domain: yourdomain.com
#    Service: http://localhost:8000
```

`https://memograph.yourdomain.com` is now live, TLS-terminated by
Cloudflare, no inbound ports opened on your network. You can close
the laptop lid; reopen it; the tunnel reconnects.

### What to put in front of MemoGraph

If you want SSO at the edge (so unauthenticated users never reach
MemoGraph at all), add a Cloudflare Access policy on the same
hostname — Google Workspace, GitHub, or generic OIDC. This is
defense in depth on top of MemoGraph's own auth.

### Pitfalls

- **Box must be on.** Obvious but worth saying. A used mini-PC or
  a Raspberry Pi 5 covers this for ~$80 one-time.
- **Backup discipline.** A drive failure on the box loses the vault.
  Run `memograph backup` on a cron and copy the tarball to Drive
  (see [GOOGLE_WORKSPACE_SETUP.md](GOOGLE_WORKSPACE_SETUP.md)) or any
  cloud bucket.

## Option C — GCP always-free stitch

For completeness. Works, but architecturally awkward for
MemoGraph's shape.

```text
Cloud Run (2M req/mo free)
    + GCS Fuse mount of a bucket  (5 GB free)
    + Firestore for auth metadata (1 GB free)
    + Cloud Build for the image    (120 build-min/day free)
```

### Why I don't recommend this as the primary path

1. **Cold starts.** Cloud Run scales to zero. Every cold start
   re-mounts GCS Fuse and re-ingests the vault. Fine at 50
   memories, painful at 5,000.
2. **GCS Fuse is slower than disk** by 10-100x on the small-file
   reads MemoGraph does during retrieval. Search latency suffers.
3. **Lock-in to GCP-specific glue** (Cloud Run, Fuse, Firestore)
   that the codebase doesn't use today; you'd be the one to
   maintain it.

When this *is* a good fit: you're already a heavy GCP shop, you
have other Cloud Run services, you accept p95 latency in the
seconds, and you want everything in one Google bill.

## Option D — GitHub repo as the vault

This works on top of any compute (A, B, or C). The vault is a
private GitHub repo. MemoGraph clones it, reads from the local
clone, and `git commit && git push` on writes.

### Why it's interesting

- **Free private repos**, unlimited count.
- **Built-in versioning** — every memory has a full revision
  history. `git blame` tells you when and why a memory changed.
- **Mobile editing** via github.com or any git-aware mobile editor.
- **Conflict resolution** is git's own; the messy two-way-sync
  semantics you'd build for Drive don't apply.
- **No quota cliff** like Drive's API limits.

### Status

This is **roadmap** as of this writing — see
[adr/0002-storage-adapter-strategy.md](adr/0002-storage-adapter-strategy.md).
A `GitVaultStorage` adapter on top of the existing `VaultStorage`
is ~1-2 weeks of work. The shape:

```python
# Today: vault is a directory.
storage = VaultStorage(vault_root="/srv/memograph/vault")

# Future: vault is a git working tree.
storage = GitVaultStorage(
    vault_root="/srv/memograph/vault",
    remote="git@github.com:you/your-vault.git",
    auto_push=True,
)
```

If you want to use this *today* without waiting for the adapter,
the rough workaround is to clone the repo into your vault dir and
run `git pull && memograph ingest && git push` on a cron. Loses
push-on-write but gets you the versioning story.

## Picking between Drive-as-portability and Drive-as-primary

Independent of the compute choice above, you have a separate
choice about how to involve the user's Google Drive.

### Drive as portability (recommended)

- Vault lives on whatever Option (A/B/C) gave you compute.
- A periodic export pushes the vault tarball to a Drive folder
  the user owns.
- User can leave at any time with their data; they own the Drive
  folder regardless of MemoGraph's state.
- **Effort**: small, mostly cron + the existing
  `memograph backup` command + a Drive upload.

### Drive as primary store

- Vault lives in the user's Drive; MemoGraph fetches files via
  the Drive API.
- Sounds great for sovereignty but breaks on quotas and latency
  unless you maintain a local cache mirror — at which point you
  haven't actually moved the storage anywhere.
- **Effort**: 4-8 engineer-weeks for a working two-way sync with
  conflict resolution and webhook-driven change detection.

The product hits 90% of the "your data lives in your Workspace"
trust story with the *portability* path at 10% of the cost. Pick
that one unless you have a hard customer ask for primary-store
Drive.

## What about the cheapest cloud-paid options?

If $5/month is acceptable, your shortlist widens:

- **Hetzner Cloud** — €4.51/mo for 2 vCPU + 4 GB + 40 GB SSD. Best
  performance per dollar in Europe.
- **Fly.io** — pay-as-you-go starting around $5/mo for a small
  always-on machine. First-class Docker support.
- **Render** — $7/mo for an always-on web service with persistent
  disk add-on.
- **DigitalOcean** — $4/mo droplet, 512 MB / 10 GB. Tight on RAM
  for embedding work; bump to $6 if you embed.

These are listed for completeness; nothing in MemoGraph requires
them. The free options are sufficient.

## Hardening checklist before you expose the box publicly

This applies regardless of which option above you pick.

```bash
# Run with auth turned on. Do NOT ship with auth=none.
export MEMOGRAPH_AUTH_PROVIDER=oidc           # or api_key
export MEMOGRAPH_OIDC_JWKS_URL=...
export MEMOGRAPH_OIDC_AUDIENCE=...
export MEMOGRAPH_OIDC_ISSUER=...

# Lock CORS to your actual frontend origin; default is "deny".
export MEMOGRAPH_CORS_ORIGINS=https://app.yourdomain.com

# Cap request bodies; default 1 MB.
export MEMOGRAPH_MAX_BODY_BYTES=1048576

# Cap vault size; bytes; soft cap warns, hard cap rejects.
export MEMOGRAPH_VAULT_SOFT_CAP=104857600     # 100 MB
export MEMOGRAPH_VAULT_HARD_CAP=524288000     # 500 MB

# Enable structured JSON logs for any aggregator (Loki, Datadog, …).
export MEMOGRAPH_LOG_JSON=1
```

Run the security workflow at least once before exposing:

```bash
ruff check . && bandit -r memograph/ && pip-audit
pytest tests/security/ tests/contract/ tests/tenancy/ --no-cov
```

Both must be green before you put a public DNS record on the box.

## Where to go next

- **[INSTALL_ENTERPRISE.md](INSTALL_ENTERPRISE.md)** — the canonical
  install doc with multi-tenancy, OIDC, observability, backup.
- **[GOOGLE_WORKSPACE_SETUP.md](GOOGLE_WORKSPACE_SETUP.md)** — wire
  Workspace identity (and optionally Drive backup) into your
  deployment.
- **[OBSERVABILITY_GUIDE.md](OBSERVABILITY_GUIDE.md)** — OTLP/Prometheus
  setup for any of the options above.
- **[GDPR_RUNBOOK.md](GDPR_RUNBOOK.md)** — what scheduled tenant
  deletion looks like in production.
