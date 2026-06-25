"""Tenant deletion reaper (Phase 3.7).

Walks the global tenant root once per invocation. For each tenant
directory containing a tombstone whose ``delete_after`` has passed,
the reaper:

1. Takes a final backup tarball under
   ``<global_root>/.tombstoned-exports/<tenant_id>-<ts>.tar.gz``.
2. Calls :meth:`TenantStorage.delete_tenant` (idempotent rm-rf).
3. Emits a JSON event line on stdout describing the outcome.

Stdout is JSON Lines; one event per tenant action. Pipe into your
log aggregator. Exit code 0 if the reaper ran to completion;
non-zero if at least one tenant failed (the others still get
processed — failures don't short-circuit).

Usage::

    python -m memograph.scripts.run_reaper <global_root>
    python -m memograph.scripts.run_reaper <global_root> --dry-run
    python -m memograph.scripts.run_reaper <global_root> --exports-dir /backups

``--dry-run`` reports what would be destroyed without taking any
action. Useful as a deploy-time sanity check or in CI.

Schedule via cron daily::

    15 3 * * * /usr/local/bin/python -m memograph.scripts.run_reaper /srv/memograph/tenants
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memograph.core.backup import create_backup
from memograph.storage.tenant_storage import TenantStorage
from memograph.storage.tombstone import (
    TombstoneError,
    read_tombstone,
)

logger = logging.getLogger("memograph.reaper")


_DEFAULT_EXPORTS_SUBDIR = ".tombstoned-exports"


def _emit(event: dict[str, Any]) -> None:
    """One JSON event per line on stdout."""
    print(json.dumps(event, sort_keys=True), flush=True)


def _exports_dir(global_root: Path, override: Path | None) -> Path:
    """Directory the final backups land in. Defaults to a hidden
    sibling of the tenant directories so it isn't itself listed by
    ``TenantStorage.list_tenants`` (which skips dot-prefixed names)."""
    target = override if override is not None else global_root / _DEFAULT_EXPORTS_SUBDIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def reap_once(
    global_root: Path,
    *,
    exports_dir: Path | None = None,
    dry_run: bool = False,
) -> int:
    """Run a single sweep. Returns the number of failures (0 = clean run)."""
    storage = TenantStorage(global_root=global_root)
    exports = _exports_dir(storage.root, exports_dir)
    failures = 0

    for tenant_id in storage.list_tenants():
        tenant_dir = storage.tenant_path(tenant_id)
        try:
            tombstone = read_tombstone(tenant_dir)
        except TombstoneError as exc:
            _emit(
                {
                    "event": "tombstone_corrupted",
                    "tenant_id": tenant_id,
                    "error": str(exc),
                }
            )
            failures += 1
            continue

        if tombstone is None:
            continue
        if not tombstone.is_expired:
            _emit(
                {
                    "event": "tombstone_pending",
                    "tenant_id": tenant_id,
                    "delete_after": tombstone.delete_after,
                }
            )
            continue

        if dry_run:
            _emit(
                {
                    "event": "would_destroy",
                    "tenant_id": tenant_id,
                    "scheduled_at": tombstone.scheduled_at,
                    "delete_after": tombstone.delete_after,
                    "reason": tombstone.reason,
                }
            )
            continue

        # Real run: backup, then destroy.
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = exports / f"{tenant_id}-{ts}.tar.gz"
        try:
            backup_path = create_backup(str(tenant_dir), str(archive))
        except Exception as exc:  # noqa: BLE001 — log + continue
            _emit(
                {
                    "event": "backup_failed",
                    "tenant_id": tenant_id,
                    "error": str(exc),
                }
            )
            failures += 1
            continue

        try:
            removed = storage.delete_tenant(tenant_id)
        except Exception as exc:  # noqa: BLE001
            _emit(
                {
                    "event": "destroy_failed",
                    "tenant_id": tenant_id,
                    "error": str(exc),
                    "backup": str(backup_path),
                }
            )
            failures += 1
            continue

        _emit(
            {
                "event": "destroyed",
                "tenant_id": tenant_id,
                "removed": removed,
                "backup": str(backup_path),
                "scheduled_at": tombstone.scheduled_at,
                "delete_after": tombstone.delete_after,
                "reason": tombstone.reason,
                "requested_by": tombstone.requested_by,
            }
        )

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="memograph.scripts.run_reaper",
        description=(
            "Destroy tenants whose tombstones have expired. Takes a "
            "final backup before each destroy."
        ),
    )
    parser.add_argument(
        "global_root",
        type=Path,
        help="Path to the multi-tenant root directory.",
    )
    parser.add_argument(
        "--exports-dir",
        type=Path,
        default=None,
        help=(
            "Directory for final backup tarballs. Default: "
            f"<global_root>/{_DEFAULT_EXPORTS_SUBDIR}/"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be destroyed without doing it.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not args.global_root.exists():
        _emit(
            {
                "event": "error",
                "message": f"global_root does not exist: {args.global_root}",
            }
        )
        return 2

    failures = reap_once(
        args.global_root,
        exports_dir=args.exports_dir,
        dry_run=args.dry_run,
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
