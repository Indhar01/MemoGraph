"""Tests for VaultStorage.move() (Step 4) and FolderAgent (Step 5).

See docs/ADR_SELF_ORGANIZING_HIERARCHY.md.
"""

from __future__ import annotations

import pytest

from memograph.core.enums import MemoryType
from memograph.core.kernel import MemoryKernel
from memograph.storage.vault import VaultStorage
from memograph.swarm.agent_base import SwarmCycleReport
from memograph.swarm.agents import FolderAgent
from memograph.swarm.config import AgentConfig, SwarmConfig
from memograph.swarm.pheromone import PheromoneMap


# --------------------------------------------------------------- VaultStorage.move


class TestVaultStorageMove:
    def test_move_into_subfolder(self, tmp_path):
        storage = VaultStorage(tmp_path)
        storage.write("note.md", "hello")
        new = storage.move("note.md", "semantic/note.md")
        assert new == (tmp_path / "semantic" / "note.md").resolve()
        assert not (tmp_path / "note.md").exists()
        assert (tmp_path / "semantic" / "note.md").read_text() == "hello"

    def test_move_missing_source_raises(self, tmp_path):
        storage = VaultStorage(tmp_path)
        with pytest.raises(FileNotFoundError):
            storage.move("nope.md", "x/nope.md")

    def test_move_onto_existing_raises(self, tmp_path):
        storage = VaultStorage(tmp_path)
        storage.write("a.md", "1")
        storage.write("b.md", "2")
        with pytest.raises(FileExistsError):
            storage.move("a.md", "b.md")

    def test_move_rejects_escape(self, tmp_path):
        storage = VaultStorage(tmp_path)
        storage.write("a.md", "1")
        with pytest.raises(ValueError):
            storage.move("a.md", "../escape.md")

    def test_move_same_path_is_noop(self, tmp_path):
        storage = VaultStorage(tmp_path)
        storage.write("a.md", "1")
        result = storage.move("a.md", "a.md")
        assert result == (tmp_path / "a.md").resolve()
        assert (tmp_path / "a.md").read_text() == "1"


# ------------------------------------------------------------------- FolderAgent


@pytest.fixture
def pheromone():
    return PheromoneMap()


def _report():
    return SwarmCycleReport(cycle_id=1)


class TestFolderAgent:
    def _kernel(self, tmp_path, strategy="by_type"):
        # Create a FLAT vault first, then attach a by_type resolver so the
        # agent has reorganization work to do.
        k = MemoryKernel(vault_path=str(tmp_path / "vault"))  # flat
        k.remember("Design Note", "content", memory_type=MemoryType.SEMANTIC)
        k.remember("Standup", "content", memory_type=MemoryType.EPISODIC)
        k.ingest(force=True)
        # Swap in the target strategy for reorganization.
        from memograph.core.hierarchy import HierarchyResolver

        k.hierarchy = HierarchyResolver(strategy)
        return k

    @pytest.mark.asyncio
    async def test_disabled_by_default(self, tmp_path, pheromone):
        k = self._kernel(tmp_path)
        cfg = SwarmConfig()
        agent = FolderAgent(k, pheromone, cfg, cfg.folder)
        assert agent.agent_config.enabled is False
        report = await agent.run_cycle(_report())
        # No actions when disabled.
        assert report.actions == []

    @pytest.mark.asyncio
    async def test_dry_run_records_but_does_not_move(self, tmp_path, pheromone):
        k = self._kernel(tmp_path)
        cfg = SwarmConfig()
        agent_cfg = AgentConfig(enabled=True, dry_run=True)
        agent = FolderAgent(k, pheromone, cfg, agent_cfg)
        report = await agent.run_cycle(_report())
        moves = [a for a in report.actions if a.action_type == "move_file"]
        assert moves, "expected planned move_file actions"
        assert all(a.dry_run and not a.applied for a in moves)
        # Files still flat on disk.
        assert (k.vault_path / "design-note.md").exists()
        assert not (k.vault_path / "semantic" / "design-note.md").exists()

    @pytest.mark.asyncio
    async def test_apply_moves_files_and_preserves_ids(self, tmp_path, pheromone):
        k = self._kernel(tmp_path)
        cfg = SwarmConfig()
        agent_cfg = AgentConfig(enabled=True, dry_run=False)
        agent = FolderAgent(k, pheromone, cfg, agent_cfg)
        report = await agent.run_cycle(_report())
        applied = [a for a in report.actions if a.applied]
        assert applied, "expected applied moves"
        # Files now live in type folders.
        assert (k.vault_path / "semantic" / "design-note.md").exists()
        assert (k.vault_path / "episodic" / "standup.md").exists()
        assert not (k.vault_path / "design-note.md").exists()
        # Re-ingest and confirm ids are unchanged (identity survived the move).
        k.ingest(force=True)
        assert k.graph.get("design-note") is not None
        assert k.graph.get("standup") is not None

    @pytest.mark.asyncio
    async def test_flat_strategy_is_noop(self, tmp_path, pheromone):
        k = self._kernel(tmp_path, strategy="flat")
        cfg = SwarmConfig()
        agent_cfg = AgentConfig(enabled=True, dry_run=False)
        agent = FolderAgent(k, pheromone, cfg, agent_cfg)
        report = await agent.run_cycle(_report())
        assert report.actions == []

    @pytest.mark.asyncio
    async def test_readonly_kernel_never_moves(self, tmp_path, pheromone):
        k = self._kernel(tmp_path)
        k.readonly = True
        cfg = SwarmConfig()
        agent_cfg = AgentConfig(enabled=True, dry_run=False)
        agent = FolderAgent(k, pheromone, cfg, agent_cfg)
        report = await agent.run_cycle(_report())
        moves = [a for a in report.actions if a.action_type == "move_file"]
        assert moves  # planned
        assert all(not a.applied for a in moves)  # but not applied
        assert (k.vault_path / "design-note.md").exists()  # unchanged

    @pytest.mark.asyncio
    async def test_wikilinks_survive_reorg(self, tmp_path, pheromone):
        k = MemoryKernel(vault_path=str(tmp_path / "vault"))  # flat
        k.remember("Event Loop", "core of async", memory_type=MemoryType.SEMANTIC)
        k.remember(
            "Async Meeting",
            "we discussed [[event-loop]]",
            memory_type=MemoryType.EPISODIC,
        )
        k.ingest(force=True)
        from memograph.core.hierarchy import HierarchyResolver

        k.hierarchy = HierarchyResolver("by_type")
        cfg = SwarmConfig()
        agent = FolderAgent(k, pheromone, cfg, AgentConfig(enabled=True, dry_run=False))
        await agent.run_cycle(_report())
        k.ingest(force=True)
        src = k.graph.get("async-meeting")
        assert src is not None
        # Edge still resolves after both files moved into different folders.
        assert "event-loop" in src.links
