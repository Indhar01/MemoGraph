"""Tenant-aware storage layout (Phase 3.1).

Built as a *new* module rather than retrofitting :class:`VaultStorage`
because today the kernel still constructs vault paths directly. When
the kernel migrates onto the storage layer (Phase 3.2 wiring),
:class:`TenantStorage` will be the orchestrator that hands kernels
their per-tenant root.

Filesystem layout::

    <global_root>/
        <tenant_id_1>/
            (per-tenant vault — markdown files, .memograph_*.json caches)
        <tenant_id_2>/
            ...

Isolation invariants enforced here (binding, per ADR 0001):

* Tenant IDs are validated against a strict pattern. No path
  separators, no NUL bytes, no Windows reserved names, no leading
  dots. Anything that could let a malicious tenant id escape its
  directory is rejected at *registration time*, not at use time.
* Each :class:`VaultStorage` returned by :meth:`for_tenant` has its
  ``root`` pointed at the tenant directory and *only* the tenant
  directory. Path-traversal defense is reused from VaultStorage: a
  write that escapes the tenant root raises ``ValueError`` before
  hitting disk.
* :meth:`delete_tenant` is a hard delete. It removes the tenant
  directory tree and is idempotent. Phase 3.7 GDPR work will layer a
  scheduled-deletion runbook on top; the primitive here just does the
  rm-rf safely.

This module deliberately does not import the kernel. The kernel will
call ``TenantStorage.for_tenant(...)`` to get a configured vault
root; the kernel itself remains tenant-unaware until Phase 3.2.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from memograph.storage.vault import VaultStorage, _FORBIDDEN_CHARS, _WINDOWS_RESERVED


_TENANT_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")
"""Tenant IDs are lowercase alnum + dash + underscore, 1–64 chars,
must start and end with an alnum (so no leading dashes or dots that
some shells would interpret as flags). Generous enough for UUIDs,
slugs, or human-readable customer IDs; restrictive enough to avoid
any imaginable path-traversal trick."""


class InvalidTenantIdError(ValueError):
    """Raised when a tenant id fails validation.

    Distinct from generic ``ValueError`` so admin-route handlers can
    map this cleanly to a 400 response without false positives from
    other validation failures.
    """


def validate_tenant_id(tenant_id: str) -> str:
    """Validate and return a tenant id, or raise.

    Rules:

    * non-empty string
    * matches ``[a-z0-9][a-z0-9_-]*[a-z0-9]`` (or a single alnum)
    * 1–64 characters
    * contains no control characters (defense in depth — the regex
      already excludes them, but if the regex is ever loosened the
      explicit check stays correct)
    * not a Windows reserved name (CON, NUL, ...)
    """
    if not isinstance(tenant_id, str):
        raise InvalidTenantIdError(
            f"tenant_id must be a string, got {type(tenant_id).__name__}"
        )
    if not tenant_id:
        raise InvalidTenantIdError("tenant_id must be non-empty")
    if any(c in _FORBIDDEN_CHARS for c in tenant_id):
        raise InvalidTenantIdError("tenant_id contains control characters")
    if not _TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise InvalidTenantIdError(
            f"tenant_id {tenant_id!r} must be 1–64 chars of "
            f"[a-z0-9_-], starting and ending with an alphanumeric"
        )
    if tenant_id.upper() in _WINDOWS_RESERVED:
        raise InvalidTenantIdError(f"tenant_id {tenant_id!r} is a reserved name")
    return tenant_id


class TenantStorage:
    """Per-tenant filesystem orchestrator.

    Owns the global root; hands out per-tenant ``VaultStorage``
    instances. Stateless beyond the root path — multiple
    ``TenantStorage`` instances pointed at the same root are safe.
    """

    def __init__(
        self,
        global_root: str | Path,
        soft_cap_bytes: int | None = None,
        hard_cap_bytes: int | None = None,
    ) -> None:
        self.root = Path(global_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._soft_cap_bytes = soft_cap_bytes
        self._hard_cap_bytes = hard_cap_bytes

    def tenant_path(self, tenant_id: str) -> Path:
        """Return the absolute path of the tenant's directory.

        Does not create the directory. Use :meth:`create_tenant` for
        registration. Validates the tenant id every call — cheap, and
        keeps the caller honest about isolation.
        """
        validate_tenant_id(tenant_id)
        candidate = (self.root / tenant_id).resolve(strict=False)
        # Defense in depth: even with the regex above, the resolved
        # path must be a direct child of the global root.
        if candidate.parent != self.root:
            raise InvalidTenantIdError(
                f"tenant_id {tenant_id!r} would escape the global root"
            )
        return candidate

    def create_tenant(self, tenant_id: str) -> Path:
        """Create the tenant directory if it doesn't exist; idempotent."""
        path = self.tenant_path(tenant_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def for_tenant(self, tenant_id: str) -> VaultStorage:
        """Return a :class:`VaultStorage` rooted at the tenant directory.

        Creates the directory on first call. The returned storage's
        ``write`` method enforces path-traversal containment within
        the tenant root — a buggy caller cannot reach a sibling
        tenant's files through this object.
        """
        path = self.create_tenant(tenant_id)
        return VaultStorage(
            vault_root=path,
            soft_cap_bytes=self._soft_cap_bytes,
            hard_cap_bytes=self._hard_cap_bytes,
        )

    def list_tenants(self) -> list[str]:
        """Return all tenant ids currently registered on disk.

        Skips dot-prefixed entries (we never create those, but the
        admin or backup tooling might).
        """
        if not self.root.exists():
            return []
        out: list[str] = []
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            try:
                validate_tenant_id(entry.name)
            except InvalidTenantIdError:
                continue
            out.append(entry.name)
        return out

    def delete_tenant(self, tenant_id: str) -> bool:
        """Hard-delete the tenant directory tree. Returns True if a
        directory was removed, False if there was nothing to delete.

        Idempotent — calling on an already-deleted tenant is fine.
        Phase 3.7 GDPR runbook will wrap this with a scheduled grace
        period and a final tarball export; this primitive only does
        the safe rm-rf.
        """
        path = self.tenant_path(tenant_id)
        if not path.exists():
            return False
        # Defensive: never recurse outside the global root, even if a
        # malicious symlink dropped into the tenant dir tries to
        # redirect us.
        if not path.is_relative_to(self.root):
            raise InvalidTenantIdError(
                f"refusing to delete {path}: outside global root"
            )
        shutil.rmtree(path)
        return True

    def usage_bytes(self, tenant_id: str) -> int:
        """Return the on-disk size of a tenant's vault, or 0 if empty.

        Wraps :meth:`VaultStorage.vault_size_bytes`. Used by admin
        usage routes and quota enforcement (when Phase 3.6 lands).
        """
        path = self.tenant_path(tenant_id)
        if not path.exists():
            return 0
        return self.for_tenant(tenant_id).vault_size_bytes()


__all__ = [
    "TenantStorage",
    "InvalidTenantIdError",
    "validate_tenant_id",
]
