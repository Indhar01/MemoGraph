"""Advisory PID lock for a MemoGraph vault.

Stdio MCP servers are single-tenant by design, but a user can accidentally
point two MCP processes (or an MCP + the Web UI worker) at the same vault.
Concurrent writers race on `.md` files and on the JSON caches the indexer
maintains, and the consequences are subtle (lost edits, stale graph).

This module implements a best-effort advisory file lock:

* A read-write server writes `<vault>/.memograph.lock` containing its PID,
  start time, hostname, and a free-form ``role`` string.
* On startup, a second server reads the file; if the PID is still alive on
  this host it refuses to start. If the PID is dead, or the host differs,
  or the file is malformed, the lock is reclaimed with a warning.
* The lock is released on normal shutdown via ``release()``; stale locks
  are tolerated so a hard kill does not leave the vault permanently
  unusable.

Read-only servers (``MEMOGRAPH_READONLY=true``) skip locking entirely — many
read-only viewers may safely share a vault.

The lock is advisory: nothing prevents a process that ignores it from
writing. It is intended to catch the common misconfiguration case, not
defeat adversarial concurrency.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LOCK_FILENAME = ".memograph.lock"


def _pid_alive(pid: int) -> bool:
    """Return True if a process with this PID exists on the current host."""
    if pid <= 0:
        return False
    try:
        # Signal 0 is the standard "does this PID exist" probe on POSIX. On
        # Windows os.kill(pid, 0) also returns without error if the PID is
        # alive, and raises OSError otherwise — both behaviors are what we
        # need here.
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # The PID exists but is owned by another user: still "alive".
        return True
    except OSError:
        return False


class VaultLockError(RuntimeError):
    """Raised when another live process already holds the vault lock."""


class VaultLock:
    """Advisory PID lock for a vault directory.

    Usage::

        lock = VaultLock(vault_path, role="mcp-server")
        lock.acquire()       # raises VaultLockError if held by another live PID
        try:
            ...
        finally:
            lock.release()
    """

    def __init__(self, vault_path: Path | str, role: str = "mcp-server") -> None:
        self.vault_path = Path(vault_path)
        self.lock_path = self.vault_path / LOCK_FILENAME
        self.role = role
        self._held = False
        # Per-instance token so two VaultLock objects in the same process do
        # not falsely treat each other as re-entrant. The on-disk file stores
        # both pid and token; only the holding instance can re-enter.
        self._token = uuid.uuid4().hex

    def _payload(self) -> dict[str, Any]:
        return {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "role": self.role,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "token": self._token,
        }

    def _read_existing(self) -> dict[str, Any] | None:
        if not self.lock_path.exists():
            return None
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "Vault lock file %s is unreadable (%s); reclaiming.",
                self.lock_path,
                e,
            )
            return None

    def acquire(self) -> None:
        existing = self._read_existing()
        if existing is not None:
            holder_pid = int(existing.get("pid", 0) or 0)
            holder_host = existing.get("host")
            holder_role = existing.get("role", "unknown")
            holder_started = existing.get("started_at", "unknown")

            same_host = holder_host == socket.gethostname()
            holder_token = existing.get("token")
            if (
                same_host
                and holder_pid == os.getpid()
                and holder_token == self._token
            ):
                # Same instance re-entering its own lock.
                self._held = True
                return

            if same_host and _pid_alive(holder_pid):
                raise VaultLockError(
                    f"Vault {self.vault_path} is already in use by another "
                    f"MemoGraph process: pid={holder_pid}, role={holder_role}, "
                    f"started_at={holder_started}. Stop that process first, or "
                    f"point this server at a different vault. If you are sure "
                    f"the holder is dead, delete {self.lock_path} manually."
                )

            logger.warning(
                "Stale vault lock for pid=%s role=%s host=%s — reclaiming.",
                holder_pid,
                holder_role,
                holder_host,
            )

        try:
            self.lock_path.write_text(
                json.dumps(self._payload(), indent=2), encoding="utf-8"
            )
            self._held = True
            logger.info("Acquired vault lock: %s", self.lock_path)
        except OSError as e:
            # If we cannot write the lock file we still want to start the
            # server — a read-only filesystem or a permissions quirk should
            # not be fatal. We just lose advisory protection.
            logger.warning(
                "Could not write vault lock (%s); continuing without "
                "concurrency protection.",
                e,
            )

    def release(self) -> None:
        if not self._held:
            return
        try:
            existing = self._read_existing()
            # Only delete the file if it's still ours — never blow away
            # another holder's lock during a paranoid double-release.
            if existing and existing.get("token") == self._token:
                self.lock_path.unlink()
                logger.info("Released vault lock: %s", self.lock_path)
        except OSError as e:
            logger.warning("Could not remove vault lock %s: %s", self.lock_path, e)
        finally:
            self._held = False

    def __enter__(self) -> VaultLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
