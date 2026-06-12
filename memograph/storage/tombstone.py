"""Tenant deletion tombstone (Phase 3.7).

A *tombstone* is a single JSON file written into a tenant directory
that marks the tenant as scheduled for deletion. The tombstone
contains:

* ``scheduled_at`` (UTC ISO-8601) — when the deletion was requested.
* ``delete_after`` (UTC ISO-8601) — the soonest the reaper may
  destroy the tenant.
* ``requested_by`` — the user id from the auth context.
* ``reason`` — optional free-text supplied by the operator.
* ``schema_version`` — currently ``1``; bumped if the format
  changes.

While a tenant is tombstoned:

* Non-admin requests resolve to **410 Gone** in the route layer.
  The kernel is still in the warm cache so the response is fast,
  but every method returns the tombstoned-state error rather than
  serving data.
* Admin requests still succeed (status checks, bring-back-from-the-dead
  cancellation, immediate destroy if the operator can't wait for
  the reaper).

The reaper (``memograph.scripts.run_reaper``) walks the global root
once per invocation. For each tenant directory containing an
expired tombstone it:

1. Takes a final backup tarball under
   ``<global_root>/.tombstoned-exports/<tenant_id>-<ts>.tar.gz``.
2. Calls ``TenantRegistry.offboard(tenant_id)`` (which evicts the
   warm kernel and ``rm -rf`` s the directory).
3. Writes a deletion-receipt line to the deployment's audit log.

This module owns only the tombstone schema + read/write/clear
primitives. The route handler and the reaper compose them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TOMBSTONE_FILENAME = "_tombstone.json"
"""Conventional filename inside a tenant directory. Underscored so it
sorts to the top in directory listings; dot-prefixing was rejected
because the existing list_tenants() pruner skips dotfiles."""

DEFAULT_GRACE_DAYS = 7
"""Default grace period if the operator doesn't override it. Long
enough that an accidental deletion can be reversed during business
hours; short enough that customers don't pay storage forever after
offboarding."""

TOMBSTONE_SCHEMA_VERSION = 1


class TombstoneError(RuntimeError):
    """Raised on malformed or corrupted tombstone files."""


@dataclass(frozen=True)
class Tombstone:
    """In-memory representation of a tombstone file."""

    schema_version: int
    scheduled_at: str
    delete_after: str
    requested_by: str
    reason: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2)

    @property
    def is_expired(self) -> bool:
        """True if the grace period has passed and the reaper may
        destroy this tenant."""
        return datetime.now(timezone.utc) >= datetime.fromisoformat(self.delete_after)


def tombstone_path(tenant_dir: Path) -> Path:
    return tenant_dir / TOMBSTONE_FILENAME


def is_tombstoned(tenant_dir: Path) -> bool:
    """Cheap existence check; does not parse the file."""
    return tombstone_path(tenant_dir).is_file()


def write_tombstone(
    tenant_dir: Path,
    *,
    requested_by: str,
    grace_days: int = DEFAULT_GRACE_DAYS,
    reason: str = "",
) -> Tombstone:
    """Write a fresh tombstone. Refuses to overwrite an existing one
    so a misclick can't reset the grace period.

    Raises :class:`TombstoneError` if the tenant is already tombstoned;
    use :func:`clear_tombstone` first if you genuinely want to reset
    the timer.
    """
    if grace_days < 0:
        raise ValueError(f"grace_days must be >= 0, got {grace_days}")
    target = tombstone_path(tenant_dir)
    if target.exists():
        raise TombstoneError(
            f"tenant at {tenant_dir} already has a tombstone; "
            "cancel it first if you want to reset the timer"
        )

    now = datetime.now(timezone.utc)
    tombstone = Tombstone(
        schema_version=TOMBSTONE_SCHEMA_VERSION,
        scheduled_at=now.isoformat(),
        delete_after=(now + timedelta(days=grace_days)).isoformat(),
        requested_by=requested_by,
        reason=reason,
    )
    tenant_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(tombstone.to_json(), encoding="utf-8")
    return tombstone


def read_tombstone(tenant_dir: Path) -> Tombstone | None:
    """Parse the tombstone, returning ``None`` if it doesn't exist
    and raising :class:`TombstoneError` if it's malformed."""
    path = tombstone_path(tenant_dir)
    if not path.is_file():
        return None
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TombstoneError(f"malformed tombstone at {path}: {exc}") from exc

    schema = raw.get("schema_version")
    if schema != TOMBSTONE_SCHEMA_VERSION:
        raise TombstoneError(
            f"tombstone at {path} has schema_version={schema!r}; "
            f"expected {TOMBSTONE_SCHEMA_VERSION}"
        )
    try:
        return Tombstone(
            schema_version=int(raw["schema_version"]),
            scheduled_at=str(raw["scheduled_at"]),
            delete_after=str(raw["delete_after"]),
            requested_by=str(raw["requested_by"]),
            reason=str(raw.get("reason", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TombstoneError(
            f"tombstone at {path} is missing required fields: {exc}"
        ) from exc


def clear_tombstone(tenant_dir: Path) -> bool:
    """Remove a tombstone, returning True if one was present.

    Used to cancel a scheduled deletion before the reaper fires.
    Idempotent: clearing a non-existent tombstone returns False.
    """
    path = tombstone_path(tenant_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


__all__ = [
    "DEFAULT_GRACE_DAYS",
    "TOMBSTONE_FILENAME",
    "TOMBSTONE_SCHEMA_VERSION",
    "Tombstone",
    "TombstoneError",
    "clear_tombstone",
    "is_tombstoned",
    "read_tombstone",
    "tombstone_path",
    "write_tombstone",
]
