"""Source-event audit log helpers.

Mirrors the pattern used by [GDPR tombstones](../storage/tombstone.py)
and the broader audit log in
[docs/GDPR_RUNBOOK.md](../../docs/GDPR_RUNBOOK.md). Every
source-mutation route in :mod:`memograph.web.backend.routes.sources`
should call :func:`record` exactly once on success, after the
mutation has been persisted.

Audit format
------------

One JSON object per line, written to ``<sources_dir>/_audit.log``:

.. code-block:: json

    {
      "ts": "2026-06-26T12:34:56.789012+00:00",
      "tenant_id": null,
      "user_id": "alice@example.com",
      "request_id": "abcdef1234567890abcdef1234567890",
      "action": "source.create",
      "source_id": "gdrive-personal",
      "source_kind": "gdrive",
      "before": null,
      "after": {"display_name": "My Drive"},
      "reason": ""
    }

The log is append-only. Rotation is the operator's job — point
``logrotate`` at the file, or read with structured-logging tooling
that handles rotation itself. We don't truncate from inside the
process because losing audit entries to a rotation race is worse
than carrying a large log file.

Failure handling
----------------

A failed audit write does NOT roll back the mutation. The mutation
already happened; failing to record it is an alert-worthy operator
incident, not a reason to undo a legitimate change. The function
logs at ``ERROR`` and returns; callers that need a hard guarantee
should run with audit-log shipping enabled separately.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Audit actions. Stable strings; never rename. Add new actions by
# appending — downstream log consumers may pattern-match on these.
ACTION_CREATE = "source.create"
ACTION_UPDATE = "source.update"
ACTION_DELETE = "source.delete"
ACTION_ACTIVATE = "source.activate"
ACTION_SYNC = "source.sync"
ACTION_OAUTH_EXCHANGE = "source.oauth_exchange"


# Module-level lock — writes to the same audit file from concurrent
# routes need to be serialized so we don't interleave half-lines.
# This is a single-process lock; multi-worker deployments rely on the
# atomic ``write()`` of a sub-PIPE_BUF-byte payload (typical audit
# line is ~400 bytes; PIPE_BUF on every supported platform is >= 512).
_LOCK = threading.Lock()


def record(
    *,
    sources_dir: Path,
    action: str,
    source_id: str,
    source_kind: str,
    user_id: str | None = None,
    tenant_id: str | None = None,
    request_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str = "",
) -> None:
    """Append one audit entry. Best-effort — never raises.

    ``sources_dir`` is the per-tenant ``.sources`` directory; the
    audit file lives next to the configs as ``_audit.log``. Each
    entry is a single JSON object on its own line (JSONL).
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "request_id": request_id,
        "action": action,
        "source_id": source_id,
        "source_kind": source_kind,
        "before": before,
        "after": after,
        "reason": reason,
    }
    line = json.dumps(entry, sort_keys=True) + "\n"

    try:
        sources_dir.mkdir(parents=True, exist_ok=True)
        path = sources_dir / "_audit.log"
        with _LOCK:
            # Open + write + close per entry. Slow but safe: every
            # entry is durable as soon as the process returns from
            # this call. If audit volume becomes a bottleneck a
            # batching writer can be added in front without changing
            # this interface.
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                # fsync is overkill for an audit log on a normal
                # workload — the OS write barrier is enough. Enable
                # via env if the operator has a strong durability
                # requirement.
                if os.environ.get("MEMOGRAPH_AUDIT_FSYNC", "").lower() in {
                    "1",
                    "true",
                    "yes",
                }:
                    os.fsync(f.fileno())
    except OSError as exc:
        # Don't let an audit failure mask the original mutation.
        # Operators monitoring the logger will see this.
        logger.error(
            "failed to record audit entry: %s; entry=%s",
            exc,
            entry,
        )


def read_entries(sources_dir: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Read audit entries newest-first.

    Test helper + admin-API helper. Reads the entire log into memory;
    for large logs callers should stream the file directly. Returns
    an empty list if no log file exists.
    """
    path = sources_dir / "_audit.log"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            # Skip corrupt lines — operator can inspect with grep.
            logger.warning("skipping malformed audit line: %s (%s)", line, exc)
    entries.reverse()
    if limit is not None:
        entries = entries[:limit]
    return entries


__all__ = [
    "ACTION_ACTIVATE",
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_OAUTH_EXCHANGE",
    "ACTION_SYNC",
    "ACTION_UPDATE",
    "read_entries",
    "record",
]
