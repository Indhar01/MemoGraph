"""Tests for Phase 1.3 storage hardening.

Covers vault_size_bytes accounting, soft/hard cap enforcement, env
overrides, and the symlink-doesn't-double-count rule.
"""

from __future__ import annotations

import os
import sys

import pytest

from memograph.storage.vault import (
    DEFAULT_HARD_CAP_BYTES,
    DEFAULT_SOFT_CAP_BYTES,
    VaultCapacityError,
    VaultStorage,
)


def test_vault_size_bytes_sums_files(tmp_path):
    vault = VaultStorage(tmp_path / "vault")
    vault.write("a.md", "x" * 100)
    vault.write("nested/b.md", "y" * 200)
    assert vault.vault_size_bytes() == 300


def test_vault_size_skips_missing_files_gracefully(tmp_path):
    vault = VaultStorage(tmp_path / "vault")
    vault.write("a.md", "x" * 50)
    # Removing the file mid-walk shouldn't crash; size goes back to 0.
    (vault.root / "a.md").unlink()
    assert vault.vault_size_bytes() == 0


def test_default_caps_sane():
    assert DEFAULT_SOFT_CAP_BYTES < DEFAULT_HARD_CAP_BYTES
    assert DEFAULT_SOFT_CAP_BYTES >= 1024 * 1024  # at least 1 MiB


def test_hard_cap_must_be_at_least_soft(tmp_path):
    with pytest.raises(ValueError, match="must be >="):
        VaultStorage(tmp_path / "v", soft_cap_bytes=100, hard_cap_bytes=50)


def test_hard_cap_blocks_write(tmp_path):
    vault = VaultStorage(tmp_path / "vault", soft_cap_bytes=50, hard_cap_bytes=100)
    vault.write("a.md", "x" * 80)  # under cap
    with pytest.raises(VaultCapacityError, match="hard cap"):
        vault.write("b.md", "y" * 50)  # would push to 130 > 100


def test_overwrite_smaller_does_not_charge_new_bytes(tmp_path):
    vault = VaultStorage(tmp_path / "vault", soft_cap_bytes=50, hard_cap_bytes=100)
    vault.write("a.md", "x" * 90)
    # Rewriting smaller content frees space, must not be rejected.
    vault.write("a.md", "x" * 10)
    assert vault.vault_size_bytes() == 10


def test_is_at_soft_cap(tmp_path):
    vault = VaultStorage(tmp_path / "vault", soft_cap_bytes=10, hard_cap_bytes=1000)
    assert not vault.is_at_soft_cap()
    vault.write("a.md", "x" * 20)
    assert vault.is_at_soft_cap()


def test_env_override_applies(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMOGRAPH_VAULT_SOFT_CAP_BYTES", "11")
    monkeypatch.setenv("MEMOGRAPH_VAULT_HARD_CAP_BYTES", "22")
    vault = VaultStorage(tmp_path / "vault")
    assert vault.soft_cap_bytes == 11
    assert vault.hard_cap_bytes == 22


def test_env_override_garbage_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMOGRAPH_VAULT_SOFT_CAP_BYTES", "not-a-number")
    monkeypatch.setenv("MEMOGRAPH_VAULT_HARD_CAP_BYTES", "-5")
    vault = VaultStorage(tmp_path / "vault")
    assert vault.soft_cap_bytes == DEFAULT_SOFT_CAP_BYTES
    assert vault.hard_cap_bytes == DEFAULT_HARD_CAP_BYTES


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Symlink creation requires admin on Windows",
)
def test_symlink_not_double_counted(tmp_path):
    # A vault containing a symlink to an outside file should not bill
    # the linked content against the cap. The pointer entry is what
    # counts (and is small).
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x" * 10_000)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    os.symlink(outside, vault_root / "ptr.bin")

    vault = VaultStorage(vault_root)
    assert vault.vault_size_bytes() == 0
