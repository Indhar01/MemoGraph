"""Migrate a single-vault 0.x deployment to the 1.0 multi-tenant layout.

Moves an existing vault directory under a global root as a named tenant
(default: ``default``), without touching file contents. After this:

- The same data is served as before, provided
  ``MEMOGRAPH_TENANCY_ENABLED=1`` and ``MEMOGRAPH_GLOBAL_ROOT=<global_root>``.
- Additional tenants can be created via ``POST /api/v1/admin/tenants``.
- A rollback is the inverse move; see ``docs/MIGRATION_0.X_TO_1.0.md``.

Usage::

    python -m memograph.scripts.migrate_to_multitenant \\
        --vault /data/vault \\
        --global-root /data/global_root \\
        [--tenant-id default] [--dry-run]

The script refuses to overwrite an existing destination directory. It
also refuses to operate on a vault that is currently being served (best
effort: looks for a ``.memograph_cache.lock`` sentinel; not a substitute
for stopping the API process yourself).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _resolve(p: str) -> Path:
    return Path(p).expanduser().resolve()


def migrate(
    vault: Path,
    global_root: Path,
    tenant_id: str,
    dry_run: bool,
) -> int:
    """Perform the move. Returns process exit code."""
    if not vault.exists():
        print(f"ERROR: vault path does not exist: {vault}", file=sys.stderr)
        return 2
    if not vault.is_dir():
        print(f"ERROR: vault path is not a directory: {vault}", file=sys.stderr)
        return 2

    lock = vault / ".memograph_cache.lock"
    if lock.exists():
        print(
            f"ERROR: vault appears to be in use ({lock} exists). Stop the "
            "API server before migrating.",
            file=sys.stderr,
        )
        return 3

    dest = global_root / tenant_id
    if dest.exists():
        print(
            f"ERROR: destination already exists: {dest}\n"
            "Refusing to merge into an existing tenant directory.",
            file=sys.stderr,
        )
        return 4

    print(f"Source vault:        {vault}")
    print(f"Global root:         {global_root}")
    print(f"Tenant id:           {tenant_id}")
    print(f"Destination:         {dest}")
    print(f"Mode:                {'DRY RUN' if dry_run else 'EXECUTE'}")

    if dry_run:
        print("\nNo changes made.")
        return 0

    global_root.mkdir(parents=True, exist_ok=True)
    shutil.move(str(vault), str(dest))
    print(f"\nMoved {vault} -> {dest}")
    print(
        "\nNext steps:\n"
        f"  export MEMOGRAPH_TENANCY_ENABLED=1\n"
        f"  export MEMOGRAPH_GLOBAL_ROOT={global_root}\n"
        "  restart the API server"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m memograph.scripts.migrate_to_multitenant",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--vault", required=True, help="Existing 0.x vault directory.")
    parser.add_argument(
        "--global-root",
        required=True,
        help="Directory that will hold per-tenant vaults under 1.0.",
    )
    parser.add_argument(
        "--tenant-id",
        default="default",
        help="Tenant id for the migrated vault (default: %(default)s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned move without performing it.",
    )

    args = parser.parse_args(argv)
    return migrate(
        vault=_resolve(args.vault),
        global_root=_resolve(args.global_root),
        tenant_id=args.tenant_id,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
