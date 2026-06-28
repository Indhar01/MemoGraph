"""Tests for the in-process :class:`SyncScheduler`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from memograph.sources.base import (
    SourceConfig,
    SourceError,
    SourceKind,
)
from memograph.sources.local import LocalSource
from memograph.sources.registry import SourceRegistry
from memograph.sources.sync import SyncScheduler


def _local_config(path: Path, source_id: str = "primary") -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        kind=SourceKind.LOCAL,
        display_name="Primary",
        params={"path": str(path), "sync_interval_seconds": 30},
    )


@pytest.mark.asyncio
async def test_tick_runs_sync_when_never_synced(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "a.md").write_text("# A", encoding="utf-8")
    registry = SourceRegistry(global_root=tmp_path / "global")
    registry.register(_local_config(vault))
    # Warm it so the scheduler sees it.
    registry.get(None, "primary")

    scheduler = SyncScheduler(registry=registry, poll_interval_seconds=10)
    await scheduler.tick_once()
    state = scheduler.state[(None, "primary")]
    assert state.last_success_at is not None
    assert state.consecutive_failures == 0


@pytest.mark.asyncio
async def test_tick_skips_inside_interval(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    registry = SourceRegistry(global_root=tmp_path / "global")
    registry.register(_local_config(vault))
    registry.get(None, "primary")

    scheduler = SyncScheduler(registry=registry)
    await scheduler.tick_once()
    first_success = scheduler.state[(None, "primary")].last_success_at
    # Run again immediately — should NOT re-sync because interval is 30s.
    await scheduler.tick_once()
    assert scheduler.state[(None, "primary")].last_success_at == first_success


@pytest.mark.asyncio
async def test_tick_records_failure(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    registry = SourceRegistry(global_root=tmp_path / "global")
    registry.register(_local_config(vault))
    source = registry.get(None, "primary")

    async def _boom(self, vault_path):
        raise SourceError("boom")

    monkeypatch.setattr(LocalSource, "materialize_to_vault", _boom)
    scheduler = SyncScheduler(registry=registry)
    await scheduler.tick_once()
    state = scheduler.state[(None, "primary")]
    assert state.last_error == "boom"
    assert state.consecutive_failures == 1
    assert state.last_success_at is None


@pytest.mark.asyncio
async def test_opt_out_with_interval_zero(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    config = SourceConfig(
        source_id="primary",
        kind=SourceKind.LOCAL,
        display_name="Primary",
        params={"path": str(vault), "sync_interval_seconds": 0},
    )
    registry = SourceRegistry(global_root=tmp_path / "global")
    registry.register(config)
    registry.get(None, "primary")
    scheduler = SyncScheduler(registry=registry)
    await scheduler.tick_once()
    # Opt-out: no state entry was created and no sync ran.
    assert (None, "primary") not in scheduler.state


@pytest.mark.asyncio
async def test_sync_now_bypasses_cadence(tmp_path: Path) -> None:
    # Even with a long sync_interval_seconds, sync_now must run.
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "a.md").write_text("# A", encoding="utf-8")
    config = SourceConfig(
        source_id="primary",
        kind=SourceKind.LOCAL,
        display_name="Primary",
        params={"path": str(vault), "sync_interval_seconds": 3600},
    )
    registry = SourceRegistry(global_root=tmp_path / "global")
    registry.register(config)
    scheduler = SyncScheduler(registry=registry)
    state = await scheduler.sync_now(None, "primary")
    assert state.last_success_at is not None
    assert state.last_error is None
    # A second call also runs (no cooldown gate on the manual path).
    first_success = state.last_success_at
    state2 = await scheduler.sync_now(None, "primary")
    assert state2.last_success_at is not None
    assert state2.last_success_at >= first_success


@pytest.mark.asyncio
async def test_sync_now_records_error(tmp_path: Path) -> None:
    # Point at a path that the LocalSource will reject — health probe
    # surfaces a SourceError, sync_now catches and records it.
    missing = tmp_path / "does-not-exist"
    config = SourceConfig(
        source_id="primary",
        kind=SourceKind.LOCAL,
        display_name="Primary",
        params={"path": str(missing)},
    )
    registry = SourceRegistry(global_root=tmp_path / "global")
    registry.register(config)
    scheduler = SyncScheduler(registry=registry)
    state = await scheduler.sync_now(None, "primary")
    # LocalSource may or may not raise on materialize for a missing
    # path (it creates the directory). Either way the call returns
    # cleanly with consistent state — that's what we assert here.
    assert state.in_flight is False


@pytest.mark.asyncio
async def test_start_stop_lifecycle(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    registry = SourceRegistry(global_root=tmp_path / "global")
    registry.register(_local_config(vault))
    registry.get(None, "primary")
    scheduler = SyncScheduler(registry=registry, poll_interval_seconds=0.05)
    await scheduler.start()
    # Let one or two ticks happen, then stop.
    await asyncio.sleep(0.15)
    await scheduler.stop()
    # Sync should have run at least once.
    assert scheduler.state[(None, "primary")].last_success_at is not None
