"""Tests for SwarmAction, SwarmCycleReport, and SwarmAgent base class."""

import pytest

from memograph.swarm.agent_base import SwarmAction, SwarmCycleReport, SwarmAgent
from memograph.swarm.config import AgentConfig, SwarmConfig
from memograph.swarm.pheromone import PheromoneMap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_kernel(tmp_path):
    """Minimal mock kernel for swarm agent testing."""
    from memograph.core.kernel import MemoryKernel

    kernel = MemoryKernel(vault_path=str(tmp_path / "vault"))
    return kernel


@pytest.fixture
def pheromone_map():
    """Fresh PheromoneMap for each test."""
    return PheromoneMap()


@pytest.fixture
def swarm_config():
    """SwarmConfig in dry_run mode for safe testing."""
    return SwarmConfig(dry_run=True)


# ---------------------------------------------------------------------------
# Concrete SwarmAgent for testing (since the base is abstract)
# ---------------------------------------------------------------------------


class ConcreteAgent(SwarmAgent):
    """Minimal concrete agent for testing the base class behaviours."""

    agent_type: str = "test_agent"

    async def run_cycle(self, report: SwarmCycleReport) -> SwarmCycleReport:
        return report


# ---------------------------------------------------------------------------
# TestSwarmAction
# ---------------------------------------------------------------------------


class TestSwarmAction:
    """Tests for [`SwarmAction`](memograph/swarm/agent_base.py:30)."""

    def test_swarm_action_creation(self):
        """Create a SwarmAction and verify all fields."""
        action = SwarmAction(
            node_id="my-note",
            agent_type="tagger",
            action_type="add_tags",
            payload={"tags": ["python"]},
            confidence=0.85,
            applied=True,
            dry_run=False,
        )
        assert action.node_id == "my-note"
        assert action.agent_type == "tagger"
        assert action.action_type == "add_tags"
        assert action.payload == {"tags": ["python"]}
        assert action.confidence == pytest.approx(0.85)
        assert action.applied is True
        assert action.dry_run is False
        assert action.error is None

    def test_swarm_action_skip(self):
        """action_type='skip' with applied=False."""
        action = SwarmAction(
            node_id="note-x",
            agent_type="linker",
            action_type="skip",
            applied=False,
        )
        assert action.action_type == "skip"
        assert action.applied is False

    def test_swarm_action_defaults(self):
        """SwarmAction has sensible defaults for optional fields."""
        action = SwarmAction(node_id="n", agent_type="gap", action_type="flag_gap")
        assert action.payload == {}
        assert action.confidence == pytest.approx(0.0)
        assert action.applied is False
        assert action.dry_run is False
        assert action.error is None
        assert action.timestamp is not None

    def test_swarm_action_to_dict(self):
        """to_dict() returns a dict with all expected keys."""
        action = SwarmAction(
            node_id="n1",
            agent_type="salience",
            action_type="boost_salience",
            payload={"boost": 0.1},
            confidence=0.7,
            applied=True,
        )
        d = action.to_dict()
        assert d["node_id"] == "n1"
        assert d["agent_type"] == "salience"
        assert d["action_type"] == "boost_salience"
        assert d["payload"] == {"boost": 0.1}
        assert d["confidence"] == pytest.approx(0.7)
        assert d["applied"] is True
        assert "timestamp" in d
        assert "error" in d

    def test_swarm_action_with_error(self):
        """SwarmAction stores the error message when set."""
        action = SwarmAction(
            node_id="n2",
            agent_type="tagger",
            action_type="add_tags",
            error="Something went wrong",
        )
        assert action.error == "Something went wrong"


# ---------------------------------------------------------------------------
# TestSwarmCycleReport
# ---------------------------------------------------------------------------


class TestSwarmCycleReport:
    """Tests for [`SwarmCycleReport`](memograph/swarm/agent_base.py:89)."""

    def test_empty_report(self):
        """SwarmCycleReport with no actions has sensible defaults."""
        report = SwarmCycleReport(cycle_id=1)
        assert report.cycle_id == 1
        assert report.actions == []
        assert report.agents_run == []
        assert report.nodes_processed == 0
        assert report.nodes_modified == 0
        assert report.errors == []
        assert report.finished_at is None
        assert report.duration_seconds is None
        assert report.dry_run is False

    def test_report_applied_actions(self):
        """applied_actions returns only actions with applied=True."""
        report = SwarmCycleReport(cycle_id=2)
        report.actions.append(
            SwarmAction(
                node_id="n1", agent_type="tagger", action_type="add_tags", applied=True
            )
        )
        report.actions.append(
            SwarmAction(
                node_id="n2", agent_type="tagger", action_type="skip", applied=False
            )
        )
        report.actions.append(
            SwarmAction(
                node_id="n3", agent_type="linker", action_type="add_links", applied=True
            )
        )

        applied = report.applied_actions
        assert len(applied) == 2
        assert all(a.applied for a in applied)

    def test_report_skipped_actions(self):
        """skipped_actions returns only actions with action_type='skip'."""
        report = SwarmCycleReport(cycle_id=3)
        report.actions.append(
            SwarmAction(
                node_id="n1", agent_type="tagger", action_type="skip", applied=False
            )
        )
        report.actions.append(
            SwarmAction(
                node_id="n2", agent_type="linker", action_type="add_links", applied=True
            )
        )

        skipped = report.skipped_actions
        assert len(skipped) == 1
        assert skipped[0].action_type == "skip"

    def test_report_finish_stamps_timestamp(self):
        """finish() sets finished_at and makes duration_seconds non-None."""
        report = SwarmCycleReport(cycle_id=4)
        assert report.finished_at is None
        report.finish()
        assert report.finished_at is not None
        assert report.duration_seconds is not None
        assert report.duration_seconds >= 0.0

    def test_report_add_error(self):
        """add_error() appends a 3-tuple to the errors list."""
        report = SwarmCycleReport(cycle_id=5)
        report.add_error("tagger", "node-x", "NLP service unavailable")
        assert len(report.errors) == 1
        agent, node, msg = report.errors[0]
        assert agent == "tagger"
        assert node == "node-x"
        assert msg == "NLP service unavailable"

    def test_report_to_dict(self):
        """to_dict() returns a dict with expected keys."""
        report = SwarmCycleReport(cycle_id=6, dry_run=True)
        report.actions.append(
            SwarmAction(
                node_id="n1", agent_type="tagger", action_type="add_tags", applied=True
            )
        )
        report.nodes_processed = 5
        report.nodes_modified = 1
        report.finish()

        d = report.to_dict()
        assert d["cycle_id"] == 6
        assert d["dry_run"] is True
        assert d["nodes_processed"] == 5
        assert d["nodes_modified"] == 1
        assert d["actions_total"] == 1
        assert d["actions_applied"] == 1
        assert "started_at" in d
        assert "finished_at" in d
        assert "duration_seconds" in d
        assert "agents_run" in d
        assert "errors" in d
        assert "pheromone_summary" in d


# ---------------------------------------------------------------------------
# TestSwarmAgent (base class helpers)
# ---------------------------------------------------------------------------


class TestSwarmAgent:
    """Tests for the [`SwarmAgent`](memograph/swarm/agent_base.py:183) base class helpers."""

    def test_agent_repr(self, mock_kernel, pheromone_map, swarm_config):
        """__repr__ includes agent_type, enabled, and dry_run."""
        agent = ConcreteAgent(
            kernel=mock_kernel,
            pheromone=pheromone_map,
            config=swarm_config,
            agent_config=swarm_config.tagger,
        )
        r = repr(agent)
        assert "test_agent" in r
        assert "enabled" in r
        assert "dry_run" in r

    def test_is_enabled_true(self, mock_kernel, pheromone_map, swarm_config):
        """_is_enabled() returns True when agent_config.enabled=True."""
        cfg = AgentConfig(enabled=True)
        agent = ConcreteAgent(mock_kernel, pheromone_map, swarm_config, cfg)
        assert agent._is_enabled() is True

    def test_is_enabled_false(self, mock_kernel, pheromone_map, swarm_config):
        """_is_enabled() returns False when agent_config.enabled=False."""
        cfg = AgentConfig(enabled=False)
        agent = ConcreteAgent(mock_kernel, pheromone_map, swarm_config, cfg)
        assert agent._is_enabled() is False

    def test_effective_dry_run_global(self, mock_kernel, pheromone_map):
        """_effective_dry_run() is True when global config.dry_run=True."""
        config = SwarmConfig(dry_run=True)
        agent_cfg = AgentConfig(dry_run=False)
        agent = ConcreteAgent(mock_kernel, pheromone_map, config, agent_cfg)
        assert agent._effective_dry_run() is True

    def test_effective_dry_run_per_agent(self, mock_kernel, pheromone_map):
        """_effective_dry_run() is True when per-agent dry_run=True (even if global=False)."""
        config = SwarmConfig(dry_run=False)
        agent_cfg = AgentConfig(dry_run=True)
        agent = ConcreteAgent(mock_kernel, pheromone_map, config, agent_cfg)
        assert agent._effective_dry_run() is True

    def test_effective_dry_run_false(self, mock_kernel, pheromone_map):
        """_effective_dry_run() is False when both global and per-agent dry_run are False."""
        config = SwarmConfig(dry_run=False)
        agent_cfg = AgentConfig(dry_run=False)
        agent = ConcreteAgent(mock_kernel, pheromone_map, config, agent_cfg)
        assert agent._effective_dry_run() is False

    def test_make_skip_action(self, mock_kernel, pheromone_map, swarm_config):
        """_make_skip_action() returns a SwarmAction with action_type='skip'."""
        agent = ConcreteAgent(
            mock_kernel, pheromone_map, swarm_config, swarm_config.tagger
        )
        skip = agent._make_skip_action("node-123", reason="no_changes_needed")
        assert skip.node_id == "node-123"
        assert skip.action_type == "skip"
        assert skip.applied is False
        assert skip.payload.get("reason") == "no_changes_needed"
        assert skip.agent_type == "test_agent"

    def test_deposit_pheromone(self, mock_kernel, pheromone_map, swarm_config):
        """_deposit_pheromone() adds a deposit to the shared PheromoneMap."""
        agent = ConcreteAgent(
            mock_kernel, pheromone_map, swarm_config, swarm_config.tagger
        )
        agent._deposit_pheromone("node-xyz", signal_type="tagged", strength=0.7)

        deps = pheromone_map.get_deposits("node-xyz")
        assert len(deps) == 1
        assert deps[0].agent_type == "test_agent"
        assert deps[0].signal_type == "tagged"
        assert deps[0].strength == pytest.approx(0.7)

    def test_candidate_nodes_empty_graph(
        self, mock_kernel, pheromone_map, swarm_config
    ):
        """_candidate_nodes() returns [] when the graph has no nodes."""
        agent = ConcreteAgent(
            mock_kernel, pheromone_map, swarm_config, swarm_config.tagger
        )
        candidates = agent._candidate_nodes()
        assert candidates == []

    @pytest.mark.asyncio
    async def test_run_cycle_returns_report(
        self, mock_kernel, pheromone_map, swarm_config
    ):
        """ConcreteAgent.run_cycle() returns the report unchanged."""
        agent = ConcreteAgent(
            mock_kernel, pheromone_map, swarm_config, swarm_config.tagger
        )
        report = SwarmCycleReport(cycle_id=1)
        result = await agent.run_cycle(report)
        assert result is report
