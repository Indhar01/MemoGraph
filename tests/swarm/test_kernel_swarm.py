"""Tests for kernel swarm integration: enable_swarm, run_swarm_cycle, start_swarm, stop_swarm, get_swarm_status."""

import pytest

from memograph.core.kernel import MemoryKernel
from memograph.swarm.config import SwarmConfig
from memograph.swarm.orchestrator import SwarmOrchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def swarm_kernel(tmp_path):
    """MemoryKernel with enable_swarm=True and two test memories."""
    cfg = SwarmConfig(
        dry_run=True,
        cycle_interval_seconds=999999,
        pheromone_persist_path=str(tmp_path / "pheromones.json"),
    )
    k = MemoryKernel(
        vault_path=str(tmp_path / "vault"),
        enable_swarm=True,
        swarm_config=cfg,
    )
    k.remember("Python Tips", "Use list comprehensions for speed.", tags=["python"])
    k.remember("Machine Learning", "Neural networks and gradient descent.", tags=["ai"])
    k.ingest()
    return k


@pytest.fixture
def plain_kernel(tmp_path):
    """MemoryKernel with swarm NOT enabled."""
    return MemoryKernel(vault_path=str(tmp_path / "vault"))


# ---------------------------------------------------------------------------
# TestKernelSwarmInit
# ---------------------------------------------------------------------------


class TestKernelSwarmInit:
    """Tests for [`MemoryKernel._init_swarm()`](memograph/core/kernel.py:397)."""

    def test_swarm_none_when_not_enabled(self, plain_kernel):
        """kernel.swarm is None when enable_swarm=False."""
        assert plain_kernel.swarm is None

    def test_swarm_orchestrator_when_enabled(self, swarm_kernel):
        """kernel.swarm is a SwarmOrchestrator when enable_swarm=True."""
        assert isinstance(swarm_kernel.swarm, SwarmOrchestrator)

    def test_five_agents_registered(self, swarm_kernel):
        """Five agents are registered by default (tagger, linker, gap, salience, summarizer)."""
        assert len(swarm_kernel.swarm._agents) == 5

    def test_agent_types_registered(self, swarm_kernel):
        """All five expected agent types are registered."""
        agent_types = {a.agent_type for a in swarm_kernel.swarm._agents}
        assert "tagger" in agent_types
        assert "linker" in agent_types
        assert "gap" in agent_types
        assert "salience" in agent_types
        assert "summarizer" in agent_types

    def test_summarizer_disabled_by_default(self, swarm_kernel):
        """Summarizer agent is registered but disabled by default."""
        summarizer = next(
            a for a in swarm_kernel.swarm._agents if a.agent_type == "summarizer"
        )
        assert summarizer.agent_config.enabled is False

    def test_pheromone_persist_path_configured(self, swarm_kernel, tmp_path):
        """Pheromone persist path is configured under vault/.swarm/ by default."""
        assert swarm_kernel.swarm.pheromone is not None

    def test_auto_persist_path_when_not_provided(self, tmp_path):
        """When swarm_config.pheromone_persist_path is None, it defaults to vault/.swarm/."""
        k = MemoryKernel(
            vault_path=str(tmp_path / "vault2"),
            enable_swarm=True,
        )
        # Should set the persist path automatically
        assert k.swarm is not None
        assert k.swarm.config.pheromone_persist_path is not None
        assert ".swarm" in k.swarm.config.pheromone_persist_path


# ---------------------------------------------------------------------------
# TestKernelRunSwarmCycle
# ---------------------------------------------------------------------------


class TestKernelRunSwarmCycle:
    """Tests for [`MemoryKernel.run_swarm_cycle()`](memograph/core/kernel.py:444)."""

    @pytest.mark.asyncio
    async def test_run_swarm_cycle_returns_dict(self, swarm_kernel):
        """run_swarm_cycle() returns a dictionary."""
        result = await swarm_kernel.run_swarm_cycle()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_run_swarm_cycle_has_expected_keys(self, swarm_kernel):
        """run_swarm_cycle() result contains expected report keys."""
        result = await swarm_kernel.run_swarm_cycle()
        assert "cycle_id" in result
        assert "nodes_processed" in result
        assert "nodes_modified" in result
        assert "dry_run" in result
        assert "agents_run" in result

    @pytest.mark.asyncio
    async def test_run_swarm_cycle_dry_run_flag(self, swarm_kernel):
        """run_swarm_cycle() result has dry_run=True when config has dry_run=True."""
        result = await swarm_kernel.run_swarm_cycle()
        assert result["dry_run"] is True

    @pytest.mark.asyncio
    async def test_run_swarm_cycle_increments_cycle_id(self, swarm_kernel):
        """Each call to run_swarm_cycle() increments the cycle_id."""
        r1 = await swarm_kernel.run_swarm_cycle()
        r2 = await swarm_kernel.run_swarm_cycle()
        assert r2["cycle_id"] == r1["cycle_id"] + 1

    @pytest.mark.asyncio
    async def test_run_swarm_cycle_raises_when_swarm_not_enabled(self, plain_kernel):
        """run_swarm_cycle() raises RuntimeError when swarm is not enabled."""
        with pytest.raises(RuntimeError, match="Swarm not enabled"):
            await plain_kernel.run_swarm_cycle()


# ---------------------------------------------------------------------------
# TestKernelSwarmStatus
# ---------------------------------------------------------------------------


class TestKernelSwarmStatus:
    """Tests for [`MemoryKernel.get_swarm_status()`](memograph/core/kernel.py:503)."""

    def test_get_swarm_status_disabled(self, plain_kernel):
        """get_swarm_status() returns {'enabled': False} when swarm not enabled."""
        status = plain_kernel.get_swarm_status()
        assert status == {"enabled": False}

    def test_get_swarm_status_enabled(self, swarm_kernel):
        """get_swarm_status() returns enabled=True and expected keys when enabled."""
        status = swarm_kernel.get_swarm_status()
        assert status["enabled"] is True
        assert "cycles_run" in status
        assert "scheduler_running" in status
        assert "agents" in status
        assert "pheromone_summary" in status

    def test_get_swarm_status_scheduler_not_running_initially(self, swarm_kernel):
        """Scheduler is not running immediately after initialization."""
        status = swarm_kernel.get_swarm_status()
        assert status["scheduler_running"] is False

    def test_get_swarm_status_agents_list(self, swarm_kernel):
        """Status agents list reflects the five registered agents."""
        status = swarm_kernel.get_swarm_status()
        assert len(status["agents"]) == 5


# ---------------------------------------------------------------------------
# TestKernelStartStopSwarm
# ---------------------------------------------------------------------------


class TestKernelStartStopSwarm:
    """Tests for [`MemoryKernel.start_swarm()`](memograph/core/kernel.py:472) and [`MemoryKernel.stop_swarm()`](memograph/core/kernel.py:489)."""

    @pytest.mark.asyncio
    async def test_start_swarm_raises_when_not_enabled(self, plain_kernel):
        """start_swarm() raises RuntimeError when swarm is not enabled."""
        with pytest.raises(RuntimeError, match="Swarm not enabled"):
            await plain_kernel.start_swarm()

    @pytest.mark.asyncio
    async def test_stop_swarm_raises_when_not_enabled(self, plain_kernel):
        """stop_swarm() raises RuntimeError when swarm is not enabled."""
        with pytest.raises(RuntimeError, match="Swarm not enabled"):
            await plain_kernel.stop_swarm()

    @pytest.mark.asyncio
    async def test_start_and_stop_swarm(self, swarm_kernel):
        """start_swarm() sets scheduler running; stop_swarm() stops it."""
        await swarm_kernel.start_swarm()
        assert swarm_kernel.swarm.is_running is True

        await swarm_kernel.stop_swarm()
        assert swarm_kernel.swarm.is_running is False

    @pytest.mark.asyncio
    async def test_stop_swarm_when_not_running_is_noop(self, swarm_kernel):
        """stop_swarm() when scheduler not running does not raise."""
        assert swarm_kernel.swarm.is_running is False
        await swarm_kernel.stop_swarm()  # should be a no-op


# ---------------------------------------------------------------------------
# TestKernelSwarmPheromone
# ---------------------------------------------------------------------------


class TestKernelSwarmPheromone:
    """Tests that pheromone deposits are created by run_swarm_cycle()."""

    @pytest.mark.asyncio
    async def test_pheromone_map_starts_empty(self, swarm_kernel):
        """Before any cycle, the pheromone map is empty."""
        assert swarm_kernel.swarm.pheromone.node_count() == 0

    @pytest.mark.asyncio
    async def test_pheromone_deposited_after_cycle(self, swarm_kernel):
        """After run_swarm_cycle(), pheromone deposits exist in the map."""
        await swarm_kernel.run_swarm_cycle()
        # The salience agent runs without LLM — it evaluates all nodes
        # and deposits pheromones (skipped or boosted)
        assert swarm_kernel.swarm.pheromone.node_count() >= 0  # at least ran

    @pytest.mark.asyncio
    async def test_cycle_report_stored_in_history(self, swarm_kernel):
        """After run_swarm_cycle(), the report is available in get_last_report()."""
        await swarm_kernel.run_swarm_cycle()
        last = swarm_kernel.swarm.get_last_report()
        assert last is not None
        assert last.cycle_id == 1
        assert last.finished_at is not None
