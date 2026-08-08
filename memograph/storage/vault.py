"""Vault storage primitives.

Phase 0 added path-traversal hardening to ``VaultStorage.write``. Phase 1.3
adds capacity awareness (``vault_size_bytes``) and configurable size caps
so a runaway client can't fill the disk.

The caps are advisory until the kernel routes through this class (Phase 3
multi-tenancy work). Today the kernel writes markdown directly via
``Path.write_text``; documenting the contract here keeps it correct as the
hot path migrates over.
"""

from __future__ import annotations

import os
from pathlib import Path

# Characters that have no business in a vault filename. NUL terminates C
# strings, the rest are control codes that filesystem tools interpret
# inconsistently. Reject early rather than rely on the OS to reject them.
_FORBIDDEN_CHARS = frozenset(chr(c) for c in range(32)) | {chr(127)}

# Windows reserved names. Even on POSIX hosts we reject them so vaults
# remain portable.
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Default size caps. Soft cap warns, hard cap rejects writes outright.
# Both can be overridden per-instance via the constructor or globally via
# ``MEMOGRAPH_VAULT_SOFT_CAP_BYTES`` / ``MEMOGRAPH_VAULT_HARD_CAP_BYTES``.
# Defaults sized for a single-tenant VPS deployment; Phase 3 multi-tenancy
# will set per-tenant caps from the tenant config.
DEFAULT_SOFT_CAP_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB
DEFAULT_HARD_CAP_BYTES = 50 * 1024 * 1024 * 1024  # 50 GiB


class VaultCapacityError(RuntimeError):
    """Raised when a write would exceed the vault's hard size cap."""


class VaultStorage:
    def __init__(
        self,
        vault_root: str | Path,
        soft_cap_bytes: int | None = None,
        hard_cap_bytes: int | None = None,
    ):
        self.root = Path(vault_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.soft_cap_bytes = (
            soft_cap_bytes
            if soft_cap_bytes is not None
            else _env_int("MEMOGRAPH_VAULT_SOFT_CAP_BYTES", DEFAULT_SOFT_CAP_BYTES)
        )
        self.hard_cap_bytes = (
            hard_cap_bytes
            if hard_cap_bytes is not None
            else _env_int("MEMOGRAPH_VAULT_HARD_CAP_BYTES", DEFAULT_HARD_CAP_BYTES)
        )
        if self.hard_cap_bytes < self.soft_cap_bytes:
            raise ValueError(
                f"hard_cap_bytes ({self.hard_cap_bytes}) must be >= "
                f"soft_cap_bytes ({self.soft_cap_bytes})"
            )

    def markdown_files(self) -> list[Path]:
        return sorted(self.root.rglob("*.md"))

    def vault_size_bytes(self) -> int:
        """Sum of file sizes under the vault root.

        Walks the tree once; expensive on large vaults but accurate.
        Callers that need this in a hot path should cache the result and
        invalidate on writes/deletes. Symlinks are *not* followed — we
        report the size of the link target only if it lives inside the
        vault, consistent with the path-traversal defense in ``write``.
        """
        total = 0
        for path in self.root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                try:
                    total += path.stat().st_size
                except OSError:
                    # File disappeared mid-walk; skip.
                    continue
        return total

    def is_at_soft_cap(self) -> bool:
        return self.vault_size_bytes() >= self.soft_cap_bytes

    def write(self, relative_path: str, content: str) -> Path:
        target = self._safe_path(relative_path)

        # Capacity check: reject if this write would push us past the
        # hard cap. Encode early so we know the on-disk byte count.
        encoded = content.encode("utf-8")
        existing_size = target.stat().st_size if target.is_file() else 0
        delta = len(encoded) - existing_size
        if delta > 0:
            current = self.vault_size_bytes()
            projected = current + delta
            if projected > self.hard_cap_bytes:
                raise VaultCapacityError(
                    f"write would exceed vault hard cap "
                    f"({projected} > {self.hard_cap_bytes} bytes)"
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        return target

    def move(self, src_relative: str, dst_relative: str) -> Path:
        """Move a file within the vault, re-validating BOTH endpoints.

        Used by the FolderAgent to reorganize existing notes into the folder
        hierarchy. Both paths are run through ``_safe_path`` so neither can
        escape the vault root (symlink or ``..`` tricks are rejected on both
        ends). The destination parent is created; empty source directories are
        left in place (cheap to prune separately, and avoids racing writers).

        Because a note's identity lives in frontmatter ``id`` (not its path),
        moving a file does NOT change its id — inbound ``[[wikilinks]]`` keep
        resolving with no rewriting. See docs/ADR_SELF_ORGANIZING_HIERARCHY.md.

        Raises:
            FileNotFoundError: if the source does not exist.
            FileExistsError: if the destination already exists.
            ValueError: if either path is unsafe.
        """
        src = self._safe_path(src_relative)
        dst = self._safe_path(dst_relative)

        if not src.is_file():
            raise FileNotFoundError(f"source is not a file: {src_relative!r}")
        if src == dst:
            return dst
        if dst.exists():
            raise FileExistsError(f"destination already exists: {dst_relative!r}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        # Path.replace is atomic on the same filesystem (POSIX + Windows).
        src.replace(dst)
        return dst

    def _safe_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError("relative_path must be a non-empty string")

        if any(c in _FORBIDDEN_CHARS for c in relative_path):
            raise ValueError("relative_path contains control characters")

        candidate = Path(relative_path)
        # Path.is_absolute() is platform-dependent: on Windows a leading "/"
        # without a drive letter is *not* absolute, so test that explicitly
        # too. We want to reject "/etc/passwd" the same way on every OS.
        if (
            candidate.is_absolute()
            or candidate.drive
            or relative_path.startswith(("/", "\\"))
        ):
            raise ValueError(f"relative_path must not be absolute: {relative_path!r}")

        for part in candidate.parts:
            if part in {"", ".", ".."}:
                # "." and "" are noise; ".." is the actual escape attempt.
                if part == "..":
                    raise ValueError(
                        f"relative_path must not traverse upward: {relative_path!r}"
                    )
            stem = part.split(".")[0].upper()
            if stem in _WINDOWS_RESERVED:
                raise ValueError(f"relative_path contains a reserved name: {part!r}")

        # resolve(strict=False) lets us handle paths that don't exist yet
        # (the common case for a write). After resolution, the result must
        # still be inside self.root — this catches symlink escapes that the
        # textual ".." check above wouldn't.
        target = (self.root / candidate).resolve(strict=False)
        if not target.is_relative_to(self.root):
            raise ValueError(f"relative_path escapes the vault root: {relative_path!r}")
        return target


def _env_int(name: str, default: int) -> int:
    """Read an env var as a positive int; fall back to default on garbage."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


__all__ = [
    "VaultStorage",
    "VaultCapacityError",
    "DEFAULT_SOFT_CAP_BYTES",
    "DEFAULT_HARD_CAP_BYTES",
]
