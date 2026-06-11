"""Path-traversal and filename-validation tests for VaultStorage.

Phase 0 (enterprise-readiness roadmap) hardening: ensure that
VaultStorage.write rejects any input that would write outside the
vault root, regardless of the technique. Even though VaultStorage.write
is currently dead code in the kernel hot path, it's the documented
storage entry point and Phase 3 multi-tenancy will route writes
through it — so the contract is enforced now.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from memograph.storage.vault import VaultStorage


@pytest.fixture
def vault(tmp_path: Path) -> VaultStorage:
    return VaultStorage(tmp_path / "vault")


class TestPathTraversal:
    def test_parent_traversal_rejected(self, vault: VaultStorage) -> None:
        with pytest.raises(ValueError, match="traverse upward"):
            vault.write("../escape.md", "x")

    def test_nested_parent_traversal_rejected(self, vault: VaultStorage) -> None:
        with pytest.raises(ValueError, match="traverse upward"):
            vault.write("subdir/../../escape.md", "x")

    def test_absolute_posix_path_rejected(self, vault: VaultStorage) -> None:
        with pytest.raises(ValueError, match="must not be absolute"):
            vault.write("/etc/passwd", "x")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific drive paths")
    def test_absolute_windows_path_rejected(self, vault: VaultStorage) -> None:
        with pytest.raises(ValueError, match="must not be absolute"):
            vault.write("C:/Windows/System32/cfg.md", "x")

    def test_nul_byte_rejected(self, vault: VaultStorage) -> None:
        with pytest.raises(ValueError, match="control characters"):
            vault.write("foo\x00.md", "x")

    def test_other_control_chars_rejected(self, vault: VaultStorage) -> None:
        # \x01–\x1f and \x7f all forbidden
        for c in ("\x01", "\x07", "\x1f", "\x7f"):
            with pytest.raises(ValueError, match="control characters"):
                vault.write(f"foo{c}.md", "x")

    def test_empty_string_rejected(self, vault: VaultStorage) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            vault.write("", "x")

    def test_non_string_rejected(self, vault: VaultStorage) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            vault.write(None, "x")  # type: ignore[arg-type]

    def test_windows_reserved_name_rejected(self, vault: VaultStorage) -> None:
        for reserved in ("CON.md", "nul.md", "lpt1.md", "subdir/aux.md"):
            with pytest.raises(ValueError, match="reserved name"):
                vault.write(reserved, "x")


class TestSymlinkEscape:
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Symlink creation requires admin on Windows",
    )
    def test_symlink_escape_rejected(self, tmp_path: Path) -> None:
        # Create a vault that contains a symlink pointing outside it.
        # If write() naively follows the symlink, the resulting absolute
        # path will land in `outside`; the post-resolve containment check
        # must catch this.
        outside = tmp_path / "outside"
        outside.mkdir()
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        os.symlink(outside, vault_root / "linked", target_is_directory=True)

        vault = VaultStorage(vault_root)
        with pytest.raises(ValueError, match="escapes the vault root"):
            vault.write("linked/owned.md", "owned")

        # Sanity: a non-symlinked write still works.
        result = vault.write("normal.md", "ok")
        assert result.read_text(encoding="utf-8") == "ok"


class TestHappyPath:
    def test_simple_write(self, vault: VaultStorage) -> None:
        path = vault.write("note.md", "hello")
        assert path.read_text(encoding="utf-8") == "hello"
        assert path.is_relative_to(vault.root)

    def test_nested_write_creates_dirs(self, vault: VaultStorage) -> None:
        path = vault.write("a/b/c/note.md", "deep")
        assert path.read_text(encoding="utf-8") == "deep"
        assert path.is_relative_to(vault.root)

    def test_dot_segments_collapsed_safely(self, vault: VaultStorage) -> None:
        # "./note.md" is a no-op `.` plus the file — should not be rejected.
        path = vault.write("./note.md", "hello")
        assert path.is_relative_to(vault.root)
