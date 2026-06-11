# GDPR runbook

Procedures for handling data-subject requests under GDPR Art. 15
(access), Art. 17 (erasure), and Art. 20 (portability).

This document is operational. Legal terminology is approximated for
clarity, not precision — your DPO has the final word on the
interpretation.

## Scope

A "data subject" in MemoGraph is the operator whose memories live in
a tenant directory. In v1, each tenant maps 1:1 to a customer
contract; one tenant = one DSR target.

If the tenant contains memories from multiple natural persons (a
shared corporate vault), erasure of one person's data is a content
problem inside the markdown, not a tenant-level operation. That case
is out of scope for this runbook; handle it manually with the
customer.

## Assumptions

- Multi-tenancy is enabled (`MEMOGRAPH_TENANCY_ENABLED=1`).
- The tenant id matches the data subject (or maps to it via a
  business-side lookup).
- The operator running these procedures has the `admin` scope.

## Right to access (Art. 15)

Produce a tarball of everything MemoGraph holds for the tenant:

```bash
TENANT_ID=acme

# 1. Snapshot the vault.
docker exec memograph-api python -m memograph.scripts.run_backup \
  /srv/memograph/tenants/$TENANT_ID \
  /srv/exports/${TENANT_ID}-$(date +%Y%m%d).tar.gz

# 2. Verify integrity.
docker exec memograph-api python -m memograph.scripts.run_backup \
  --verify /srv/exports/${TENANT_ID}-$(date +%Y%m%d).tar.gz

# 3. Hand the tarball to the data subject via your secure-delivery
# mechanism. Log the handoff in your DSR tracker.
```

The tarball contains:

- Every markdown file in the tenant vault.
- Cache files (`.memograph_*.json`) — derived data, but included
  for completeness.
- Per-tenant action log (`audit/`) — who-did-what within the
  tenant.
- The backup manifest with sha256 of every file.

It does not contain:

- Embedding model weights — those are model-side IP and not
  data-subject data.
- Other tenants' data — `TenantStorage` enforces filesystem
  isolation, see [adr/0001-tenancy-model.md](adr/0001-tenancy-model.md).

## Right to portability (Art. 20)

The tarball produced above is the portability artifact. The format
is documented in `memograph/core/backup.py`:

- A `manifest.json` at the root with version, created_at, and the
  list of (path, size, sha256) tuples.
- All vault files at their original relative paths.

Any system that can parse markdown + YAML frontmatter can ingest
this tarball. We deliberately do not gate portability behind a
proprietary format.

## Right to erasure (Art. 17)

The destructive primitive is the admin offboard route. In v1.0 it's
immediate; in v1.1 (Phase 3.7) it becomes a scheduled deletion with
a configurable grace period.

### Today (immediate deletion)

```bash
TENANT_ID=acme
ADMIN_JWT=...

# 1. Final export FIRST (do not skip this — the deletion is
# irreversible and you may need the export for legal evidence
# of what was deleted).
docker exec memograph-api python -m memograph.scripts.run_backup \
  /srv/memograph/tenants/$TENANT_ID \
  /srv/exports/${TENANT_ID}-final-$(date +%Y%m%d).tar.gz

# 2. Offboard.
curl -fsS -X DELETE \
  https://memograph.example.com/api/v1/admin/tenants/$TENANT_ID \
  -H "Authorization: Bearer $ADMIN_JWT"

# 3. Verify gone.
curl -fsS https://memograph.example.com/api/v1/admin/tenants/$TENANT_ID \
  -H "Authorization: Bearer $ADMIN_JWT"
# Expect: 404.

# 4. Verify the directory is removed on disk.
test ! -d /srv/memograph/tenants/$TENANT_ID && echo "ok: directory removed"

# 5. Verify no stale entry in any cache. The kernel evicts the
# warm slot on offboard, so this should be clean — but if you've
# customized the deployment, double-check:
docker exec memograph-api python -c "
from memograph.core.tenant_registry import TenantRegistry
# (instantiate as you do in production)
print(registry.warm_tenants())
print(registry.known_tenants())
"
```

### What gets deleted

- Everything under `<global_root>/<tenant_id>/`. That includes
  markdown files, cache files, action log, and any files put there
  by integrations.
- The warm kernel for the tenant is evicted from the LRU and its
  graph + embedding cache are dropped from RAM.

### What does *not* get deleted

- Backup tarballs you have created of the tenant. These are your
  responsibility — purge them per your data retention policy.
- Per-vault copies of memories that integrations (Obsidian, Notion)
  may have synced *out* of MemoGraph. Coordinate with the
  customer's IT to remove those from the destination system.
- Application logs that recorded the tenant's activity. Logs are
  shipped to your log aggregator; purge them per your aggregator's
  retention.
- Metrics. Prometheus counters carry the tenant_id label; old
  samples remain until the retention window expires. Do not relax
  this — Prometheus is not designed for selective deletion.

## Confirmation letter template

For your records, after each erasure:

```
Subject: Confirmation of data erasure

Per your request dated <date>, MemoGraph data associated with
tenant_id <tenant_id> was erased on <date> at <time> UTC.

Specifically removed:
  - Tenant vault directory: <global_root>/<tenant_id>/
  - All markdown files within (including embedded content)
  - Cache files (.memograph_*.json)
  - Per-tenant action log

A final export tarball was produced before deletion and is held
in our records under <export_id> for legal-defense purposes per
our data retention policy.

Backup tarballs older than <date - retention_days> have been
purged on schedule.
```

## Pending Phase 3.7: scheduled deletion

The current immediate-delete behavior is operationally fine but
has two failure modes the customer's legal team will eventually ask
about:

1. **Mistaken request.** No grace period to recover.
2. **Atomic guarantee.** A crash mid-`offboard` could leave a
   half-deleted tenant. The current implementation is robust
   against this (`shutil.rmtree` retries; the warm-cache eviction
   is independent of the disk operation), but there is no
   end-of-deletion sentinel.

Phase 3.7 adds:

- `POST /api/v1/admin/tenants/{id}/schedule-delete` with a
  configurable grace period (default 7 days).
- A `deleted_at` field on the tenant record that turns the
  tenant into "tombstoned" — non-admin routes 410 Gone.
- A daily reaper that runs the destructive primitive on tombstoned
  tenants past grace.
- Deletion sentinel files written before and after the destructive
  step so the operator can audit the half-state.

When that lands, this runbook will be updated to call the scheduled
endpoint instead of the immediate one.
