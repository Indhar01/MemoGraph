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

Two paths exist:

- **Scheduled deletion (preferred).** Schedule a deletion with a
  grace period; the reaper script destroys the tenant after the
  grace expires, taking a final backup automatically. Survives a
  mistaken request and is the standard GDPR flow.
- **Immediate deletion (emergency).** A single destructive call
  with no recovery window. Use only when the operator has already
  taken the final backup out-of-band and accepts the irreversibility.

### Scheduled deletion (preferred)

```bash
TENANT_ID=acme
ADMIN_JWT=...

# 1. Schedule the deletion. Grace period defaults to 7 days; pass
# grace_days=N to override. The reason is recorded on the tombstone
# for audit.
curl -fsS -X POST \
  https://memograph.example.com/api/v1/admin/tenants/$TENANT_ID/schedule-delete \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"grace_days": 7, "reason": "GDPR Art. 17 ticket #4242"}'
# Expect 202 Accepted with the scheduled_at / delete_after timestamps.

# 2. The tenant is now tombstoned. Non-admin requests return 410:
curl -i https://memograph.example.com/api/v1/memories \
  -H "X-API-Key: $TENANT_API_KEY"
# Expect: HTTP/1.1 410 Gone

# 3. Admin status check still works — the tombstone metadata is
# visible on the tenant record:
curl -fsS https://memograph.example.com/api/v1/admin/tenants/$TENANT_ID \
  -H "Authorization: Bearer $ADMIN_JWT" | jq
# Expect: {"tenant_id": "acme", "tombstoned": true,
#          "tombstone_scheduled_at": "...", "tombstone_delete_after": "..."}

# 4. The reaper runs daily (cron) and destroys expired tombstones.
# It writes a final backup to <global_root>/.tombstoned-exports/
# before destroying the tenant. To trigger manually:
docker exec memograph-api python -m memograph.scripts.run_reaper \
  /srv/memograph/tenants
# Stdout is JSON Lines; one event per tenant action. Pipe into your
# log aggregator.

# 5. Verify destruction.
test ! -d /srv/memograph/tenants/$TENANT_ID && echo "ok: directory removed"
ls /srv/memograph/tenants/.tombstoned-exports/${TENANT_ID}-*.tar.gz
# Expect: a tarball matching <tenant_id>-<UTC timestamp>.tar.gz.
```

#### Cancelling a scheduled deletion

If a customer requests cancellation before the grace expires (mistake,
legal hold, change of heart), clear the tombstone:

```bash
curl -fsS -X DELETE \
  https://memograph.example.com/api/v1/admin/tenants/$TENANT_ID/schedule-delete \
  -H "Authorization: Bearer $ADMIN_JWT"
# Expect: 204 No Content.
```

The tenant immediately resumes serving non-admin requests. No data
was lost; the kernel was warm in the LRU the whole time.

#### Reaper cron schedule

```cron
# /etc/cron.d/memograph-reaper
15 3 * * * memograph-ops /usr/local/bin/python -m memograph.scripts.run_reaper /srv/memograph/tenants >> /var/log/memograph/reaper.jsonl 2>&1
```

#### Reaper dry-run

Use `--dry-run` to audit what *would* be destroyed without doing it.
Useful in CI and during operator training:

```bash
python -m memograph.scripts.run_reaper /srv/memograph/tenants --dry-run
```

Stdout will contain `would_destroy` events for each tenant whose
grace has expired; nothing on disk is changed.

### Immediate deletion (emergency)

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

```text
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

## Future work

- Per-data-subject erasure within a shared corporate vault. Today
  the runbook is tenant-scoped (one tenant = one DSR target). When
  multiple natural persons share a tenant, content-level erasure
  is a manual markdown-editing job. A future runbook will document
  a tooling-assisted flow.
- Deletion-receipt signing. The reaper currently emits a JSON event;
  a future enhancement will sign each receipt with a deployment-side
  key so the operator can hand customers a cryptographically
  verifiable proof of erasure.
