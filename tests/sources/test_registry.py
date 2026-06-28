"""Tests for :class:`memograph.sources.registry.SourceRegistry`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from memograph.sources.base import (
    Source,
    SourceConfig,
    SourceError,
    SourceKind,
)
from memograph.sources.local import LocalSource
from memograph.sources.registry import (
    InvalidSourceIdError,
    SourceRegistry,
    default_source_factory,
    validate_source_id,
)


def _config(
    source_id: str = "primary",
    tenant_id: str | None = None,
    path: Path | None = None,
) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        kind=SourceKind.LOCAL,
        display_name=source_id.replace("-", " ").title(),
        tenant_id=tenant_id,
        params={"path": str(path)} if path else {},
    )


class TestValidateSourceId:
    @pytest.mark.parametrize(
        "valid",
        ["primary", "gdrive-personal", "a", "abc_123", "_" * 0 + "x"],
    )
    def test_valid(self, valid: str) -> None:
        # "abc_123" → valid (underscore allowed). "a" → 1 char.
        # Skip the "" case because min length is 1.
        if valid == "":
            return
        assert validate_source_id(valid) == valid

    @pytest.mark.parametrize(
        "invalid",
        ["UPPER", "has space", "has/slash", "has.dot", "", "a" * 65, "ünicode"],
    )
    def test_rejects(self, invalid: str) -> None:
        with pytest.raises(InvalidSourceIdError):
            validate_source_id(invalid)


class TestRegisterAndGet:
    def test_round_trip(self, tmp_path: Path) -> None:
        vault = tmp_path / "v1"
        vault.mkdir()
        registry = SourceRegistry(global_root=tmp_path / "global")
        config = _config(path=vault)
        source = registry.register(config)
        assert isinstance(source, LocalSource)
        assert source.source_id == "primary"
        # Second get should hit the warm cache without rebuilding.
        again = registry.get(None, "primary")
        assert again is source

    def test_re_register_overwrites(self, tmp_path: Path) -> None:
        a = tmp_path / "a"; a.mkdir()
        b = tmp_path / "b"; b.mkdir()
        registry = SourceRegistry(global_root=tmp_path / "global")
        registry.register(_config(path=a))
        # Re-register with a different path; the warm slot should be
        # invalidated so get() rebuilds with the new config.
        registry.register(
            _config(path=b),
        )
        source = registry.get(None, "primary")
        # LocalSource exposes the path indirectly via params; verify
        # by reading the persisted config.
        persisted = registry.get_config(None, "primary")
        assert persisted is not None
        assert persisted.params["path"] == str(b)

    def test_get_unknown_raises(self, tmp_path: Path) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        with pytest.raises(SourceError, match="source not found"):
            registry.get(None, "nonexistent")

    def test_get_config_missing_returns_none(self, tmp_path: Path) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        assert registry.get_config(None, "nope") is None


class TestPersistence:
    def test_config_persists_to_disk(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"; vault.mkdir()
        global_root = tmp_path / "global"
        registry = SourceRegistry(global_root=global_root)
        registry.register(_config(path=vault))
        on_disk = global_root / ".sources" / "primary.json"
        assert on_disk.exists()
        raw: dict[str, Any] = json.loads(on_disk.read_text(encoding="utf-8"))
        assert raw["source_id"] == "primary"
        assert raw["kind"] == "local"

    def test_loads_existing_config_from_fresh_registry(
        self, tmp_path: Path
    ) -> None:
        # Register, throw away the registry, build a new one against
        # the same global_root, get the source — it should be there.
        vault = tmp_path / "v"; vault.mkdir()
        global_root = tmp_path / "global"
        SourceRegistry(global_root=global_root).register(_config(path=vault))
        fresh = SourceRegistry(global_root=global_root)
        source = fresh.get(None, "primary")
        assert isinstance(source, LocalSource)


class TestListConfigs:
    def test_lists_alphabetically(self, tmp_path: Path) -> None:
        v1 = tmp_path / "v1"; v1.mkdir()
        v2 = tmp_path / "v2"; v2.mkdir()
        registry = SourceRegistry(global_root=tmp_path / "global")
        registry.register(_config("zeta", path=v1))
        registry.register(_config("alpha", path=v2))
        configs = registry.list_configs(None)
        ids = [c.source_id for c in configs]
        assert ids == ["alpha", "zeta"]

    def test_empty_when_no_sources_dir(self, tmp_path: Path) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        assert registry.list_configs(None) == []

    def test_skips_corrupt_files(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"; vault.mkdir()
        global_root = tmp_path / "global"
        registry = SourceRegistry(global_root=global_root)
        registry.register(_config(path=vault))
        # Drop a corrupt file next to the good one.
        (global_root / ".sources" / "broken.json").write_text("not json")
        configs = registry.list_configs(None)
        # Only the good one survives; the corrupt one is logged + skipped.
        assert [c.source_id for c in configs] == ["primary"]


class TestActiveSource:
    def test_set_and_get(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"; vault.mkdir()
        registry = SourceRegistry(global_root=tmp_path / "global")
        registry.register(_config(path=vault))
        assert registry.get_active(None) is None
        registry.set_active(None, "primary")
        assert registry.get_active(None) == "primary"

    def test_cannot_activate_unknown(self, tmp_path: Path) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        with pytest.raises(SourceError, match="cannot activate unknown"):
            registry.set_active(None, "nope")

    def test_delete_clears_active(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"; vault.mkdir()
        registry = SourceRegistry(global_root=tmp_path / "global")
        registry.register(_config(path=vault))
        registry.set_active(None, "primary")
        assert registry.get_active(None) == "primary"
        registry.delete(None, "primary")
        assert registry.get_active(None) is None


class TestDelete:
    def test_idempotent(self, tmp_path: Path) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        # Deleting something that doesn't exist returns False, doesn't raise.
        assert registry.delete(None, "nothing-here") is False

    def test_removes_disk_and_warm(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"; vault.mkdir()
        global_root = tmp_path / "global"
        registry = SourceRegistry(global_root=global_root)
        registry.register(_config(path=vault))
        # Get warms the source.
        registry.get(None, "primary")
        assert (None, "primary") in list(registry.warm_keys())
        assert registry.delete(None, "primary") is True
        assert (None, "primary") not in list(registry.warm_keys())
        assert not (global_root / ".sources" / "primary.json").exists()


class TestMultiTenantIsolation:
    def test_same_id_different_tenants(self, tmp_path: Path) -> None:
        v_a = tmp_path / "a"; v_a.mkdir()
        v_b = tmp_path / "b"; v_b.mkdir()
        global_root = tmp_path / "global"
        registry = SourceRegistry(global_root=global_root)
        registry.register(_config("primary", tenant_id="tenant-a", path=v_a))
        registry.register(_config("primary", tenant_id="tenant-b", path=v_b))
        # Each tenant sees only its own source.
        assert [c.source_id for c in registry.list_configs("tenant-a")] == ["primary"]
        assert [c.source_id for c in registry.list_configs("tenant-b")] == ["primary"]
        a_path = registry.get_config("tenant-a", "primary").params["path"]  # type: ignore[union-attr]
        b_path = registry.get_config("tenant-b", "primary").params["path"]  # type: ignore[union-attr]
        assert a_path != b_path

    def test_tenant_isolation_holds_on_disk(self, tmp_path: Path) -> None:
        v_a = tmp_path / "a"; v_a.mkdir()
        global_root = tmp_path / "global"
        registry = SourceRegistry(global_root=global_root)
        registry.register(_config("primary", tenant_id="tenant-a", path=v_a))
        # Tenant directory must be under <global_root>/<tenant_id>/.sources/
        # so the existing TenantStorage layout is respected.
        assert (global_root / "tenant-a" / ".sources" / "primary.json").exists()


class TestLRUEviction:
    def test_evicts_at_capacity(self, tmp_path: Path) -> None:
        global_root = tmp_path / "global"
        registry = SourceRegistry(global_root=global_root, max_warm=2)
        for name in ("a", "b", "c"):
            v = tmp_path / name; v.mkdir()
            registry.register(_config(name, path=v))
        # After registering three with capacity 2, only the latest two
        # are warm.
        warm_ids = {sid for _, sid in registry.warm_keys()}
        assert len(warm_ids) == 2
        # The least recently used one was evicted.
        assert "a" not in warm_ids


class TestFactoryDispatch:
    def test_cloud_kinds_require_registry_context(self) -> None:
        # Cloud OAuth kinds (gdrive, onedrive, notion) need a
        # NangoClient injected, which only the registry has at
        # construction time. Calling the bare factory is a
        # programming error — surface it loudly.
        for kind in (SourceKind.GDRIVE, SourceKind.ONEDRIVE, SourceKind.NOTION):
            config = SourceConfig(
                source_id="x",
                kind=kind,
                display_name="x",
            )
            with pytest.raises(SourceError, match="SourceRegistry"):
                default_source_factory(config)

    def test_cloud_kind_without_nango_client_raises(self, tmp_path: Path) -> None:
        # Through the registry, but no nango_client injected — the
        # operator never wired Nango up. Surface a clear setup error
        # rather than crashing later at first proxy call.
        registry = SourceRegistry(global_root=tmp_path / "global")
        config = SourceConfig(
            source_id="x",
            kind=SourceKind.GDRIVE,
            display_name="x",
            params={"nango_connection_id": "conn-1"},
        )
        with pytest.raises(SourceError, match="MEMOGRAPH_NANGO_BASE_URL"):
            # register() warms the source immediately by calling get(),
            # so the misconfiguration surfaces here without a separate
            # get() call.
            registry.register(config)

    def test_local_dispatch(self, tmp_path: Path) -> None:
        v = tmp_path / "v"; v.mkdir()
        source = default_source_factory(_config(path=v))
        assert isinstance(source, LocalSource)
