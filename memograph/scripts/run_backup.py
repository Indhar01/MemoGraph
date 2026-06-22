"""Backup CLI for the production-compose backup sidecar.

Usage::

    python -m memograph.scripts.run_backup <vault_path> <destination>

Wraps :func:`memograph.core.backup.create_backup`. Emits a single JSON
line to stdout describing the resulting archive — easy to pipe into
log aggregation or alert if missing.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from memograph.core.backup import create_backup


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 2:
        print(
            "usage: python -m memograph.scripts.run_backup <vault> <dest>",
            file=sys.stderr,
        )
        return 2

    vault, dest = args
    try:
        archive = create_backup(vault, dest)
    except Exception as exc:  # pragma: no cover — trivial CLI
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                    "type": type(exc).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "archive": str(archive),
                "size_bytes": archive.stat().st_size,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
