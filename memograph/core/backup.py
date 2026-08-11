"""Versioned vault backup format with integrity verification.

The existing ``kernel.create_backup`` zips up markdown files with no
manifest, no schema version, and no integrity check — so a corrupted
or partial archive looks identical to a healthy one. This module
introduces a forward-compatible format that can survive future
schema changes (kernel cache layout, swarm pheromone state,
per-tenant scoping in Phase 3).

Archive layout (tar.gz)::

    manifest.json              # written first; readers can verify before extracting
    vault/<...>.md             # all .md files under the vault root, paths preserved

``manifest.json`` schema::

    {
      "format_version": 1,
      "memograph_version": "0.3.0",
      "created_at": "2026-04-21T12:34:56+00:00",
      "vault_name": "my-vault",
      "file_count": 42,
      "total_bytes": 123456,
      "files": {
        "note.md": {"sha256": "...", "size": 1234},
        "subdir/other.md": {"sha256": "...", "size": 567},
        ...
      }
    }

``restore_backup`` refuses to write any file whose hash diverges from
the manifest, and refuses to extract from a manifest with a future
``format_version``. This is deliberate — silently restoring a partial
or downgraded backup is a worse failure mode than a noisy abort.

Phase 3 multi-tenancy work will extend the manifest with
``tenant_id``; the structure is already a dict so adding fields is
backwards-compatible.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKUP_FORMAT_VERSION = 1
"""Bump when the manifest schema or archive layout changes."""

_MANIFEST_NAME = "manifest.json"
_VAULT_PREFIX = "vault/"
_HASH_BLOCK_SIZE = 65_536


class BackupError(RuntimeError):
    """Generic backup/restore failure."""


class BackupCorruptedError(BackupError):
    """Raised when manifest hashes don't match the file contents on restore."""


class BackupVersionError(BackupError):
    """Raised when the manifest declares a format version newer than this build."""


@dataclass(frozen=True)
class FileEntry:
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {"sha256": self.sha256, "size": self.size}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FileEntry:
        return cls(sha256=str(raw["sha256"]), size=int(raw["size"]))


@dataclass
class BackupManifest:
    format_version: int
    memograph_version: str
    created_at: str
    vault_name: str
    files: dict[str, FileEntry] = field(default_factory=dict)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(e.size for e in self.files.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "memograph_version": self.memograph_version,
            "created_at": self.created_at,
            "vault_name": self.vault_name,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "files": {p: e.to_dict() for p, e in self.files.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BackupManifest:
        if "format_version" not in raw:
            raise BackupError("manifest missing format_version")
        version = int(raw["format_version"])
        if version > BACKUP_FORMAT_VERSION:
            raise BackupVersionError(
                f"backup format_version {version} is newer than this "
                f"build supports ({BACKUP_FORMAT_VERSION}); upgrade memograph"
            )
        files = {
            str(p): FileEntry.from_dict(e) for p, e in raw.get("files", {}).items()
        }
        return cls(
            format_version=version,
            memograph_version=str(raw.get("memograph_version", "")),
            created_at=str(raw.get("created_at", "")),
            vault_name=str(raw.get("vault_name", "")),
            files=files,
        )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(_HASH_BLOCK_SIZE), b""):
            h.update(block)
    return h.hexdigest()


def _memograph_version() -> str:
    try:
        from memograph import __version__

        return __version__
    except ImportError:  # pragma: no cover
        return "unknown"


def create_backup(vault_path: str | Path, destination: str | Path) -> Path:
    """Build a versioned tar.gz backup of the vault.

    Includes only ``*.md`` files. Cache files
    (``.memograph_cache.json``, ``.memograph_graph.json``,
    ``.memograph_embeddings.json``) are excluded — they regenerate from
    source markdown and shipping them would bloat the archive without
    adding fidelity.

    Returns the path to the resulting ``.tar.gz``.
    """
    vault_root = Path(vault_path).expanduser().resolve()
    dest = Path(destination).expanduser()
    if not vault_root.is_dir():
        raise BackupError(f"vault path is not a directory: {vault_root}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    backup_name = f"{vault_root.name}_backup_{timestamp}.tar.gz"
    # Treat dest as a directory when it already exists as one OR when
    # it doesn't exist and has no .tar.gz / .tgz suffix. This lets
    # callers pass `./backups` and have us auto-name the archive
    # without first creating the dir.
    looks_like_archive = dest.suffix in {".gz", ".tgz"} or dest.name.endswith(".tar.gz")
    if (dest.exists() and dest.is_dir()) or (
        not dest.exists() and not looks_like_archive
    ):
        dest.mkdir(parents=True, exist_ok=True)
        archive_path = dest / backup_name
    else:
        archive_path = dest
        archive_path.parent.mkdir(parents=True, exist_ok=True)

    files: dict[str, FileEntry] = {}
    for md in sorted(vault_root.rglob("*.md")):
        if not md.is_file() or md.is_symlink():
            continue
        rel = md.relative_to(vault_root).as_posix()
        files[rel] = FileEntry(sha256=_sha256_file(md), size=md.stat().st_size)

    manifest = BackupManifest(
        format_version=BACKUP_FORMAT_VERSION,
        memograph_version=_memograph_version(),
        created_at=datetime.now(timezone.utc).isoformat(),
        vault_name=vault_root.name,
        files=files,
    )

    logger.info(
        "creating backup: vault=%s files=%d bytes=%d -> %s",
        vault_root,
        manifest.file_count,
        manifest.total_bytes,
        archive_path,
    )

    with tarfile.open(archive_path, "w:gz") as tar:
        # Manifest first so a streaming reader can verify before extracting.
        manifest_bytes = json.dumps(manifest.to_dict(), indent=2).encode("utf-8")
        info = tarfile.TarInfo(name=_MANIFEST_NAME)
        info.size = len(manifest_bytes)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        tar.addfile(info, BytesIO(manifest_bytes))

        for rel in sorted(files):
            src = vault_root / rel
            tar.add(src, arcname=f"{_VAULT_PREFIX}{rel}")

    return archive_path


def read_manifest(archive_path: str | Path) -> BackupManifest:
    """Extract just the manifest from a backup. Cheap; no file contents read."""
    archive = Path(archive_path).expanduser()
    if not archive.is_file():
        raise BackupError(f"backup archive not found: {archive}")
    with tarfile.open(archive, "r:gz") as tar:
        try:
            info = tar.getmember(_MANIFEST_NAME)
        except KeyError as exc:
            raise BackupError(
                f"archive does not contain {_MANIFEST_NAME}; not a memograph backup"
            ) from exc
        f = tar.extractfile(info)
        if f is None:
            raise BackupError("manifest entry could not be read")
        raw = json.loads(f.read().decode("utf-8"))
    return BackupManifest.from_dict(raw)


def verify_backup(archive_path: str | Path) -> BackupManifest:
    """Read the archive and check every file's sha256 against the manifest.

    Returns the manifest on success; raises :class:`BackupCorruptedError`
    on the first mismatch with both the path and (truncated) hash diff
    so an operator can find the corrupt entry.
    """
    archive = Path(archive_path).expanduser()
    manifest = read_manifest(archive)

    seen: set[str] = set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name == _MANIFEST_NAME:
                continue
            if not member.name.startswith(_VAULT_PREFIX):
                # Unknown entry — not necessarily fatal, but suspicious.
                logger.warning("ignoring unexpected entry in backup: %s", member.name)
                continue
            rel = member.name[len(_VAULT_PREFIX) :]
            seen.add(rel)
            if rel not in manifest.files:
                raise BackupCorruptedError(
                    f"file in archive but not in manifest: {rel!r}"
                )
            f = tar.extractfile(member)
            if f is None:
                raise BackupCorruptedError(f"could not read member {rel!r}")
            h = hashlib.sha256()
            for block in iter(lambda: f.read(_HASH_BLOCK_SIZE), b""):
                h.update(block)
            actual = h.hexdigest()
            expected = manifest.files[rel].sha256
            if actual != expected:
                raise BackupCorruptedError(
                    f"sha256 mismatch for {rel!r}: "
                    f"manifest={expected[:12]}... actual={actual[:12]}..."
                )

    missing = set(manifest.files) - seen
    if missing:
        raise BackupCorruptedError(
            f"manifest declares {len(missing)} file(s) not present in "
            f"archive: e.g. {sorted(missing)[0]!r}"
        )
    return manifest


def restore_backup(
    archive_path: str | Path,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> BackupManifest:
    """Restore a backup into ``destination``, verifying integrity first.

    The destination directory is created if missing. If it exists and
    contains files, ``overwrite=False`` aborts to prevent silent
    clobbering of a different vault.

    Path traversal in archive entries is rejected before write — an
    archive crafted with ``../etc/passwd`` cannot escape the
    destination root.
    """
    manifest = verify_backup(archive_path)
    archive = Path(archive_path).expanduser()
    dest = Path(destination).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)

    if not overwrite and any(list(dest.iterdir())):
        raise BackupError(
            f"destination is not empty: {dest}; pass overwrite=True to merge"
        )

    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.name.startswith(_VAULT_PREFIX):
                continue
            rel = member.name[len(_VAULT_PREFIX) :]
            target = (dest / rel).resolve()
            if not target.is_relative_to(dest):
                raise BackupError(
                    f"archive entry {member.name!r} escapes the destination root"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            f = tar.extractfile(member)
            if f is None:
                continue
            target.write_bytes(f.read())

    logger.info(
        "restored backup: archive=%s files=%d -> %s",
        archive,
        manifest.file_count,
        dest,
    )
    return manifest


__all__ = [
    "BACKUP_FORMAT_VERSION",
    "BackupError",
    "BackupCorruptedError",
    "BackupVersionError",
    "BackupManifest",
    "FileEntry",
    "create_backup",
    "read_manifest",
    "verify_backup",
    "restore_backup",
]
