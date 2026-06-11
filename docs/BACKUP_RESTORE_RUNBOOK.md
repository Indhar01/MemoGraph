# Backup & restore runbook

The vault is the source of truth. If you can restore the vault, you
can restore MemoGraph. Caches and embeddings are derived data; they
will rebuild themselves from the vault on first startup after
restore.

This runbook covers:

1. The backup format and integrity guarantees.
2. How the production compose stack runs the backup sidecar.
3. How to restore from a backup.
4. The disaster-recovery test that verifies your backups work
   *before* you need them.

## Backup format

Backups are produced by `memograph/core/backup.py` (Phase 2.4).

- `tar.gz` archive containing every file under the vault root.
- `manifest.json` at the archive root with:
  - `format_version` (currently 1).
  - `created_at` (UTC ISO-8601).
  - `vault_root` (path at backup time, advisory).
  - `files`: list of `{path, size, sha256}` tuples.
- Integrity: every file is hashed at backup time. Restore verifies
  every hash before extracting; a single mismatch aborts the restore
  and leaves the destination untouched.
- Path traversal: the restore code rejects any archive whose entries
  resolve outside the destination root. Defense against malicious or
  corrupted archives.

## Production compose

`deploy/docker-compose.production.yml` includes a `backup` sidecar
that runs `memograph.scripts.run_backup` on a cron schedule.

```yaml
backup:
  image: ghcr.io/indhar01/memograph:<tag>
  command: >
    sh -c 'while true; do
      python -m memograph.scripts.run_backup
        /vault
        /backups/$$(date +%Y%m%d-%H%M%S).tar.gz
      sleep 3600
    done'
  volumes:
    - vault-data:/vault:ro
    - ./backups:/backups
```

Adjust the cadence (`sleep 3600`) and the destination path to your
needs. The sidecar mounts the vault read-only — if a backup ever
corrupts the vault, the sidecar didn't do it.

For multi-tenant deployments, point the sidecar at the global root
and the resulting backup contains every tenant. Per-tenant backups
are produced via the GDPR runbook flow (one tarball per tenant).

## Restore

```bash
# 1. Stop the API so nothing writes during restore.
docker compose -f deploy/docker-compose.production.yml stop memograph

# 2. Move the existing vault aside (do not rm — keep it as a
# fallback in case restore fails).
mv /srv/memograph/vault /srv/memograph/vault.broken-$(date +%s)
mkdir -p /srv/memograph/vault
chown 1000:1000 /srv/memograph/vault

# 3. Verify the backup before extracting.
docker run --rm -v /srv/memograph/backups:/backups \
  ghcr.io/indhar01/memograph:<tag> \
  python -m memograph.core.backup verify /backups/2026-06-11-0300.tar.gz

# 4. Restore.
docker run --rm \
  -v /srv/memograph/backups:/backups \
  -v /srv/memograph/vault:/vault \
  ghcr.io/indhar01/memograph:<tag> \
  python -m memograph.core.backup restore /backups/2026-06-11-0300.tar.gz /vault

# 5. Bring the API back up.
docker compose -f deploy/docker-compose.production.yml up -d memograph

# 6. Wait for /readyz, then smoke-test.
curl -fsS https://memograph.example.com/readyz
curl -fsS -H "X-API-Key: $KEY" https://memograph.example.com/api/v1/memories | jq '.total'
# Expected: same total as before the incident.
```

If the restore fails (manifest mismatch, partial extract), the
destination is left untouched and the broken-old vault is still
under `/srv/memograph/vault.broken-<ts>`. You can either retry with
a different backup or fall back to the broken vault for forensic
analysis.

## DR drill

Run this quarterly. The point is to verify that the backups you have
*can actually restore the system* — most backup outages are
discovered the day you need them.

1. Spin up a clean staging environment (separate compose project,
   different vault directory, different ports).
2. Copy the most recent production backup tarball to the staging
   host.
3. Run the restore steps above against the staging vault.
4. Hit `/api/v1/memories` and confirm the total matches production.
5. Pick three random memory IDs from production, fetch them on
   staging, diff the bodies — they must be byte-identical.
6. Document the run in your DR log: timestamp, backup id, total
   memories, time-to-restore.

If any step fails, fix it *before* the next production incident.
The fix is usually a small permission/path issue that compounds in
production.

## Backup retention

Decide your retention by how far back you might need to recover:

| Cadence | Keep | Use case |
|---|---|---|
| Hourly | 48 hours | Recent corruption / accidental delete |
| Daily | 30 days | Most operational incidents |
| Weekly | 12 weeks | Quarterly DR drill, schema-change rollback |
| Monthly | 12 months | Compliance evidence, year-over-year audit |

Storage cost scales linearly with retention. A 1 GB vault → 1 GB
per backup. Consider compression-aware storage (s3 with intelligent
tiering, restic, etc.) if you're keeping more than a few hundred
backups.

## Off-host storage

The compose sidecar writes backups to a local volume. That's the
minimum; for actual disaster recovery you need them off-host:

- **AWS S3**: lifecycle the local `./backups` directory to S3 with
  `aws s3 sync` on the same cron.
- **rclone**: works for S3, GCS, Azure Blob, Backblaze, and most
  WebDAV.
- **borgmatic / restic**: encrypted off-site backups with built-in
  retention policy.

A backup that lives only on the same host as the database is not a
backup. Treat the local directory as a staging area; the real
backup is wherever the off-host copy lands.

## Encryption at rest

Backups inherit whatever filesystem-level encryption the host
provides. We do not encrypt at the archive level today because:

- Encryption-at-rest is a host concern (LUKS / EBS encryption / etc.)
  in the v1 architecture.
- Per-tenant KMS-managed keys are Phase 5 (compliance) work.

If your customer requires "backup must be encrypted with our key,"
either:

- Land Phase 5 BYOK first, or
- Pipe the tarball through `gpg --encrypt -r <recipient>` between
  `run_backup` and the off-host upload.

## What to test in CI

The Phase 2.4 test suite in `tests/security/test_backup.py` covers:

- Round-trip integrity (backup → restore → byte-identical).
- Tampered manifest is rejected.
- Path-traversal entries are rejected.
- Format-version mismatch produces a clear error.

Run these as part of every release. A backup format that passes
review-board today and fails restore tomorrow is a worse outcome
than no backup at all.
