"""Tests for the Phase 2.4 versioned backup format.

Round-trip semantics, integrity detection (corrupted archive +
truncated manifest), version-skew refusal, path-traversal escape
defense, and the overwrite=False guard against silent vault clobber.
"""

from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memograph.core.backup import (
    BACKUP_FORMAT_VERSION,
    BackupCorruptedError,
    BackupError,
    BackupVersionError,
    create_backup,
    read_manifest,
    restore_backup,
    verify_backup,
)


@pytest.fixture
def populated_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\nFirst note.\n", encoding="utf-8")
    (vault / "subdir").mkdir()
    (vault / "subdir" / "beta.md").write_text("# Beta\n\n[[alpha]]\n", encoding="utf-8")
    # Cache files we expect the backup to skip.
    (vault / ".memograph_cache.json").write_text("{}", encoding="utf-8")
    return vault


def test_create_then_round_trip(tmp_path, populated_vault):
    archive = create_backup(populated_vault, tmp_path / "backups")
    assert archive.exists()
    assert archive.suffix == ".gz"

    restore_dir = tmp_path / "restored"
    manifest = restore_backup(archive, restore_dir)

    assert manifest.format_version == BACKUP_FORMAT_VERSION
    assert manifest.file_count == 2
    # Cache files were excluded.
    assert ".memograph_cache.json" not in manifest.files

    assert (restore_dir / "alpha.md").read_text(encoding="utf-8").startswith("# Alpha")
    assert (
        (restore_dir / "subdir" / "beta.md")
        .read_text(encoding="utf-8")
        .startswith("# Beta")
    )


def test_verify_passes_on_pristine_archive(tmp_path, populated_vault):
    archive = create_backup(populated_vault, tmp_path)
    manifest = verify_backup(archive)
    assert manifest.file_count == 2


def test_read_manifest_does_not_extract(tmp_path, populated_vault):
    archive = create_backup(populated_vault, tmp_path)
    manifest = read_manifest(archive)
    assert manifest.vault_name == "vault"
    assert manifest.format_version == BACKUP_FORMAT_VERSION


def test_corrupted_archive_detected(tmp_path, populated_vault):
    """Tamper with one file's payload; verify_backup must raise."""
    archive = create_backup(populated_vault, tmp_path / "out.tar.gz")

    # Build a fresh archive with the manifest from the original but a
    # mutated alpha.md body.
    with tarfile.open(archive, "r:gz") as src:
        manifest_member = src.getmember("manifest.json")
        manifest_bytes = src.extractfile(manifest_member).read()
        # Replace alpha.md with truncated content.
        members = src.getmembers()
        bodies = {}
        for m in members:
            f = src.extractfile(m)
            bodies[m.name] = f.read() if f is not None else b""

    bodies["vault/alpha.md"] = b"corrupted!"

    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered, "w:gz") as out:
        # Manifest first, original.
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        out.addfile(info, io.BytesIO(manifest_bytes))
        for name, body in bodies.items():
            if name == "manifest.json":
                continue
            info = tarfile.TarInfo(name)
            info.size = len(body)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            out.addfile(info, io.BytesIO(body))

    with pytest.raises(BackupCorruptedError, match="sha256 mismatch"):
        verify_backup(tampered)


def test_future_format_version_rejected(tmp_path):
    """An archive whose manifest declares a newer format must abort."""
    future = {
        "format_version": BACKUP_FORMAT_VERSION + 1,
        "memograph_version": "future",
        "created_at": "2099-01-01T00:00:00+00:00",
        "vault_name": "v",
        "files": {},
    }
    archive = tmp_path / "future.tar.gz"
    raw = json.dumps(future).encode("utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        tar.addfile(info, io.BytesIO(raw))

    with pytest.raises(BackupVersionError):
        verify_backup(archive)


def test_archive_without_manifest_rejected(tmp_path, populated_vault):
    """An archive missing manifest.json must fail on read_manifest."""
    bad = tmp_path / "no-manifest.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        # Just put a bare file in.
        body = b"hello"
        info = tarfile.TarInfo("vault/x.md")
        info.size = len(body)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        tar.addfile(info, io.BytesIO(body))
    with pytest.raises(BackupError, match="not a memograph backup"):
        read_manifest(bad)


def test_path_traversal_in_archive_rejected(tmp_path):
    """An archive entry with .. must not escape the destination root.

    This protects against malicious backups planted by an attacker who
    can write to the backup directory.
    """
    # Hand-craft a manifest that matches the malicious entry's hash.
    body = b"owned"
    import hashlib

    manifest = {
        "format_version": BACKUP_FORMAT_VERSION,
        "memograph_version": "test",
        "created_at": "2026-01-01T00:00:00+00:00",
        "vault_name": "evil",
        "files": {
            "../escape.md": {
                "sha256": hashlib.sha256(body).hexdigest(),
                "size": len(body),
            }
        },
    }

    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        raw = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        tar.addfile(info, io.BytesIO(raw))

        info = tarfile.TarInfo("vault/../escape.md")
        info.size = len(body)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        tar.addfile(info, io.BytesIO(body))

    with pytest.raises(BackupError, match="escapes the destination root"):
        restore_backup(archive, tmp_path / "restored")


def test_restore_into_nonempty_dir_blocked_unless_overwrite(tmp_path, populated_vault):
    archive = create_backup(populated_vault, tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "preexisting.txt").write_text("hi", encoding="utf-8")

    with pytest.raises(BackupError, match="destination is not empty"):
        restore_backup(archive, dest)

    # overwrite=True merges and returns the manifest.
    manifest = restore_backup(archive, dest, overwrite=True)
    assert manifest.file_count == 2
    assert (dest / "preexisting.txt").exists()  # left alone
    assert (dest / "alpha.md").exists()
