"""Phase 3.1 isolation tests for :class:`TenantStorage`.

Bar (per ADR 0001):

* Tenant ids that could escape the global root are rejected.
* Files written for tenant A never appear in tenant B's vault.
* Hard-delete of one tenant leaves all sibling tenants byte-identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memograph.storage.tenant_storage import (
    InvalidTenantIdError,
    TenantStorage,
    validate_tenant_id,
)


@pytest.fixture
def storage(tmp_path):
    return TenantStorage(global_root=tmp_path)


# ---- validate_tenant_id ----


@pytest.mark.parametrize(
    "tid",
    [
        "acme",
        "tenant-1",
        "tenant_1",
        "a",
        "0",
        "00000000-0000-0000-0000-000000000000".replace(
            "-", "_"
        ),  # uuid-ish, 32 chars within range
    ],
)
def test_validate_tenant_id_accepts_valid(tid):
    assert validate_tenant_id(tid) == tid


@pytest.mark.parametrize(
    "tid,reason",
    [
        ("", "empty"),
        ("..", "traversal"),
        ("../etc", "traversal with slash"),
        ("/etc", "absolute"),
        ("\\etc", "windows absolute"),
        ("a" * 65, "too long"),
        ("-leading-dash", "leading dash"),
        ("trailing-dash-", "trailing dash"),
        (".dotfile", "leading dot"),
        ("Tenant", "uppercase"),
        ("tenant.id", "dot in body"),
        ("tenant id", "space"),
        ("tenant\x00id", "nul byte"),
        ("CON", "windows reserved"),
        ("nul", "windows reserved lowercase"),
    ],
)
def test_validate_tenant_id_rejects(tid, reason):
    with pytest.raises(InvalidTenantIdError):
        validate_tenant_id(tid)


def test_validate_tenant_id_rejects_non_string():
    with pytest.raises(InvalidTenantIdError):
        validate_tenant_id(None)  # type: ignore[arg-type]
    with pytest.raises(InvalidTenantIdError):
        validate_tenant_id(123)  # type: ignore[arg-type]


# ---- tenant_path / create_tenant ----


def test_tenant_path_under_root(storage, tmp_path):
    path = storage.tenant_path("acme")
    assert path == (tmp_path / "acme").resolve()


def test_tenant_path_does_not_create(storage):
    path = storage.tenant_path("acme")
    assert not path.exists()


def test_create_tenant_creates_directory(storage):
    path = storage.create_tenant("acme")
    assert path.is_dir()


def test_create_tenant_idempotent(storage):
    a = storage.create_tenant("acme")
    b = storage.create_tenant("acme")
    assert a == b
    assert b.is_dir()


# ---- for_tenant ----


def test_for_tenant_returns_isolated_vault(storage):
    a = storage.for_tenant("acme")
    b = storage.for_tenant("globex")

    a.write("note.md", "secret-acme")
    b.write("note.md", "secret-globex")

    assert (a.root / "note.md").read_text() == "secret-acme"
    assert (b.root / "note.md").read_text() == "secret-globex"
    # Cross-tenant: acme has no view of globex's note.
    assert "globex" not in {p.parent.name for p in a.markdown_files()}


def test_for_tenant_blocks_path_traversal(storage):
    a = storage.for_tenant("acme")
    with pytest.raises(ValueError):
        a.write("../globex/oops.md", "x")
    # Defense in depth: even with a non-existent target, the parent
    # didn't get created.
    assert not (storage.root / "globex").exists()


# ---- list_tenants ----


def test_list_tenants_empty(storage):
    assert storage.list_tenants() == []


def test_list_tenants_returns_sorted(storage):
    storage.create_tenant("zeta")
    storage.create_tenant("alpha")
    storage.create_tenant("mu")
    assert storage.list_tenants() == ["alpha", "mu", "zeta"]


def test_list_tenants_skips_dotdirs(storage, tmp_path):
    storage.create_tenant("acme")
    (tmp_path / ".cache").mkdir()
    assert storage.list_tenants() == ["acme"]


def test_list_tenants_skips_invalid_names(storage, tmp_path):
    storage.create_tenant("acme")
    # Manually create a directory with a name that wouldn't validate;
    # list should silently skip it rather than crash.
    (tmp_path / "Bad-Name-Caps").mkdir()
    assert storage.list_tenants() == ["acme"]


# ---- delete_tenant ----


def test_delete_tenant_removes_tree(storage):
    a = storage.for_tenant("acme")
    a.write("note.md", "x")
    assert storage.delete_tenant("acme") is True
    assert not (storage.root / "acme").exists()


def test_delete_tenant_idempotent(storage):
    assert storage.delete_tenant("ghost") is False
    assert storage.delete_tenant("ghost") is False


def test_delete_tenant_isolation(storage):
    a = storage.for_tenant("acme")
    b = storage.for_tenant("globex")
    a.write("a.md", "secret-acme")
    b.write("b.md", "secret-globex")

    storage.delete_tenant("acme")

    # globex must be byte-identical.
    assert (b.root / "b.md").read_text() == "secret-globex"
    assert storage.list_tenants() == ["globex"]


def test_delete_tenant_rejects_invalid_id(storage):
    with pytest.raises(InvalidTenantIdError):
        storage.delete_tenant("../etc")


# ---- usage_bytes ----


def test_usage_bytes_zero_for_missing(storage):
    assert storage.usage_bytes("ghost") == 0


def test_usage_bytes_grows_with_writes(storage):
    a = storage.for_tenant("acme")
    a.write("note.md", "x" * 100)
    # Account for filesystem reporting differences.
    assert storage.usage_bytes("acme") >= 100


# ---- isolation under list operation ----


def test_markdown_files_only_lists_own_tenant(storage):
    a = storage.for_tenant("acme")
    b = storage.for_tenant("globex")
    a.write("only-in-acme.md", "x")
    b.write("only-in-globex.md", "y")

    a_files = {Path(p).name for p in a.markdown_files()}
    b_files = {Path(p).name for p in b.markdown_files()}

    assert a_files == {"only-in-acme.md"}
    assert b_files == {"only-in-globex.md"}
