"""Tests for SwarmOrchestrator (memograph/swarm/orchestrator.py)."""

import pytest

from memograph.swarm.agent_base import SwarmAction, SwarmAgent, SwarmCycleReport
from memograph.swarm.config import AgentConfig, SwarmConfig
from memograph.swarm.orchestrator import SwarmOrchestrator
from memograph.swarm.pheromone import PheromoneMap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kernel(tmp_path):
    """MemoryKernel with two test memories for orchestrator tests."""
    from memograph.core.kernel import MemoryKernel

    k = MemoryKernel(vault_path=str(tmp_path / "vault"))
    k.remember(
        "Python Tips", "Use list comprehensions. [[machine-learning]]", tags=["python"]
    )
    k.remember(
        "Machine Learning", "Neural networks and deep learning.", tags=["ai", "ml"]
    )
    k.ingest()
    return k


@pytest.fixture
def swarm_config(tmp_path):
    """SwarmConfig in dry_run mode with a very long cycle_interval to prevent auto-scheduling."""
    return SwarmConfig(
        dry_run=True,
        cycle_interval_seconds=999999,
        pheromone_persist_path=str(tmp_path / "pheromones.json"),
    )


@pytest.fixture
def orchestrator(kernel, swarm_config):
    """SwarmOrchestrator with no agents registered."""
    return SwarmOrchestrator(kernel=kernel, config=swarm_config)


# ---------------------------------------------------------------------------
# Minimal concrete agent for testing
# ---------------------------------------------------------------------------


class MockSwarmAgent(SwarmAgent):
    """Minimal no-op agent that records which nodes it was called on."""

    agent_type: str = "mock_agent"

    def __init__(self, kernel, pheromone, config, agent_config, *, side_effect=None):
        super().__init__(kernel, pheromone, config, agent_config)
        self._side_effect = side_effect
        self.call_count = 0

    async def run_cycle(self, report: SwarmCycleReport) -> SwarmCycleReport:
        self.call_count += 1
        if self._side_effect is not None:
            raise self._side_effect
        return report


# ---------------------------------------------------------------------------
# TestSwarmOrchestrator
# ---------------------------------------------------------------------------


class TestSwarmOrchestrator:
    """Tests for [`SwarmOrchestrator`](memograph/swarm/orchestrator.py:27)."""

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def test_init(self, kernel, swarm_config):
        """Orchestrator creates pheromone_map and starts with empty _agents list."""
        orc = SwarmOrchestrator(kernel=kernel, config=swarm_config)
        assert isinstance(orc.pheromone, PheromoneMap)
        assert orc._agents == []
        assert orc._cycle_count == 0
        assert orc.is_running is False

    def test_init_creates_pheromone_map(self, kernel, swarm_config):
        """A PheromoneMap is always created on init."""
        orc = SwarmOrchestrator(kernel=kernel, config=swarm_config)
        assert orc.pheromone is not None

    def test_init_accepts_existing_pheromone_map(self, kernel, swarm_config):
        """A pre-existing PheromoneMap can be injected at init."""
        pmap = PheromoneMap()
        pmap.deposit("node-x", "tagger", "tagged", strength=0.5)
        orc = SwarmOrchestrator(kernel=kernel, config=swarm_config, pheromone_map=pmap)
        assert orc.pheromone is pmap
        assert orc.pheromone.node_count() == 1

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def test_register_agent(self, orchestrator, kernel, swarm_config):
        """register() adds an agent to _agents."""
        agent = MockSwarmAgent(
            kernel, orchestrator.pheromone, swarm_config, swarm_config.tagger
        )
        orchestrator.register(agent)
        assert len(orchestrator._agents) == 1
        assert orchestrator._agents[0] is agent

    def test_register_sorts_by_priority(self, orchestrator, kernel, swarm_config):
        """Agents are sorted by priority descending after registration."""
        cfg_low = AgentConfig(priority=0.2)
        cfg_mid = AgentConfig(priority=0.5)
        cfg_high = AgentConfig(priority=0.9)

        a_low = MockSwarmAgent(kernel, orchestrator.pheromone, swarm_config, cfg_low)
        a_mid = MockSwarmAgent(kernel, orchestrator.pheromone, swarm_config, cfg_mid)
        a_high = MockSwarmAgent(kernel, orchestrator.pheromone, swarm_config, cfg_high)

        orchestrator.register(a_low)
        orchestrator.register(a_high)
        orchestrator.register(a_mid)

        priorities = [a.agent_config.priority for a in orchestrator._agents]
        assert priorities == sorted(priorities, reverse=True)

    def test_unregister_agent(self, orchestrator, kernel, swarm_config):
        """unregister() removes all agents of the given type."""
        agent = MockSwarmAgent(
            kernel, orchestrator.pheromone, swarm_config, swarm_config.tagger
        )
        orchestrator.register(agent)
        assert len(orchestrator._agents) == 1

        removed = orchestrator.unregister("mock_agent")
        assert removed == 1
        assert orchestrator._agents == []

    def test_unregister_nonexistent_returns_zero(self, orchestrator):
        """unregister() returns 0 when no matching agent is found."""
        removed = orchestrator.unregister("nonexistent_type")
        assert removed == 0

    def test_get_agents_returns_copy(self, orchestrator, kernel, swarm_config):
        """get_agents() returns a copy — mutating it does not affect the orchestrator."""
        agent = MockSwarmAgent(
            kernel, orchestrator.pheromone, swarm_config, swarm_config.tagger
        )
        orchestrator.register(agent)
        agents = orchestrator.get_agents()
        agents.clear()
        assert len(orchestrator._agents) == 1

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def test_status_no_agents(self, orchestrator):
        """status() returns expected keys with agents=[] and cycles_run=0."""
        s = orchestrator.status()
        assert s["cycles_run"] == 0
        assert s["scheduler_running"] is False
        assert s["agents"] == []
        assert "pheromone_summary" in s
        assert s["last_cycle"] is None
        assert "config" in s

    def test_status_with_registered_agent(self, orchestrator, kernel, swarm_config):
        """status() agents list reflects registered agents."""
        agent = MockSwarmAgent(
            kernel, orchestrator.pheromone, swarm_config, swarm_config.tagger
        )
        orchestrator.register(agent)
        s = orchestrator.status()
        assert len(s["agents"]) == 1
        assert s["agents"][0]["type"] == "mock_agent"

    # ------------------------------------------------------------------
    # run_cycle
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_run_cycle_empty_agents(self, orchestrator):
        """run_cycle() with no agents returns a completed report."""
        report = await orchestrator.run_cycle()
        assert isinstance(report, SwarmCycleReport)
        assert report.cycle_id == 1
        assert report.finished_at is not None
        assert report.agents_run == []

    @pytest.mark.asyncio
    async def test_run_cycle_increments_counter(self, orchestrator):
        """Each run_cycle() call increments _cycle_count."""
        await orchestrator.run_cycle()
        await orchestrator.run_cycle()
        assert orchestrator._cycle_count == 2

    @pytest.mark.asyncio
    async def test_run_cycle_calls_enabled_agent(
        self, orchestrator, kernel, swarm_config
    ):
        """run_cycle() calls run_cycle() on each enabled agent."""
        cfg = AgentConfig(enabled=True)
        agent = MockSwarmAgent(kernel, orchestrator.pheromone, swarm_config, cfg)
        orchestrator.register(agent)

        await orchestrator.run_cycle()
        assert agent.call_count == 1

    @pytest.mark.asyncio
    async def test_run_cycle_skips_disabled_agent(
        self, orchestrator, kernel, swarm_config
    ):
        """run_cycle() does NOT call disabled agents."""
        cfg = AgentConfig(enabled=False)
        agent = MockSwarmAgent(kernel, orchestrator.pheromone, swarm_config, cfg)
        orchestrator.register(agent)

        await orchestrator.run_cycle()
        assert agent.call_count == 0

    @pytest.mark.asyncio
    async def test_run_cycle_agent_exception_recorded_in_report(
        self, orchestrator, kernel, swarm_config
    ):
        """An exception in an agent is captured in report.errors, not re-raised."""
        cfg = AgentConfig(enabled=True)
        agent = MockSwarmAgent(
            kernel,
            orchestrator.pheromone,
            swarm_config,
            cfg,
            side_effect=ValueError("test error"),
        )
        orchestrator.register(agent)

        report = await orchestrator.run_cycle()
        assert len(report.errors) == 1
        assert "test error" in report.errors[0][2]

    @pytest.mark.asyncio
    async def test_run_cycle_report_in_history(self, orchestrator):
        """Completed reports are stored in report history."""
        await orchestrator.run_cycle()
        assert orchestrator.get_last_report() is not None
        assert len(orchestrator.get_report_history()) == 1

    @pytest.mark.asyncio
    async def test_run_cycle_nodes_modified_count(
        self, orchestrator, kernel, swarm_config
    ):
        """nodes_modified is the count of unique node IDs with applied=True."""

        class ApplyingAgent(SwarmAgent):
            agent_type: str = "applier"

            async def run_cycle(self, report):
                report.actions.append(
                    SwarmAction(
                        node_id="n1",
                        agent_type="applier",
                        action_type="add_tags",
                        applied=True,
                    )
                )
                report.actions.append(
                    SwarmAction(
                        node_id="n1",
                        agent_type="applier",
                        action_type="add_tags",
                        applied=True,
                    )
                )
                report.actions.append(
                    SwarmAction(
                        node_id="n2",
                        agent_type="applier",
                        action_type="add_tags",
                        applied=True,
                    )
                )
                return report

        agent = ApplyingAgent(
            kernel, orchestrator.pheromone, swarm_config, swarm_config.tagger
        )
        orchestrator.register(agent)
        report = await orchestrator.run_cycle()
        # n1 and n2 are modified — 2 unique node IDs
        assert report.nodes_modified == 2

    # ------------------------------------------------------------------
    # Background scheduler
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_start_stop_scheduler(self, orchestrator):
        """start() launches the background task; stop() cancels it."""
        assert orchestrator.is_running is False
        orchestrator.start()
        assert orchestrator.is_running is True
        await orchestrator.stop()
        assert orchestrator.is_running is False

    @pytest.mark.asyncio
    async def test_start_twice_raises(self, orchestrator):
        """Calling start() twice raises RuntimeError."""
        orchestrator.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                orchestrator.start()
        finally:
            await orchestrator.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running_is_noop(self, orchestrator):
        """stop() when scheduler is not running does not raise."""
        assert orchestrator.is_running is False
        await orchestrator.stop()  # should be a no-op

    # ------------------------------------------------------------------
    # Report persistence (with report_persist_path configured)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_run_cycle_saves_report_to_disk(self, kernel, tmp_path):
        """Cycle reports are saved to disk when report_persist_path is set."""
        report_dir = tmp_path / "reports"
        config = SwarmConfig(
            dry_run=True,
            cycle_interval_seconds=999999,
            report_persist_path=str(report_dir),
        )
        orc = SwarmOrchestrator(kernel=kernel, config=config)
        await orc.run_cycle()

        saved_files = list(report_dir.glob("cycle_*.json"))
        assert len(saved_files) == 1

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def test_repr(self, orchestrator):
        """__repr__ includes agent count and cycle count."""
        r = repr(orchestrator)
        assert "SwarmOrchestrator" in r
        assert "agents=" in r
        assert "cycles=" in r
