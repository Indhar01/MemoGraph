"""Tests for SwarmConfig and AgentConfig (memograph/swarm/config.py)."""

import pytest

from memograph.swarm.config import AgentConfig, SwarmConfig


class TestAgentConfig:
    """Tests for the [`AgentConfig`](memograph/swarm/config.py:7) dataclass."""

    def test_default_agent_config(self):
        """Verify AgentConfig defaults: enabled=True, priority=0.5, confidence_threshold=0.6."""
        cfg = AgentConfig()
        assert cfg.enabled is True
        assert cfg.priority == pytest.approx(0.5)
        assert cfg.max_nodes_per_cycle == 20
        assert cfg.confidence_threshold == pytest.approx(0.6)
        assert cfg.dry_run is False

    def test_custom_agent_config(self):
        """Create AgentConfig with custom values and verify them."""
        cfg = AgentConfig(
            enabled=False,
            priority=0.9,
            max_nodes_per_cycle=50,
            confidence_threshold=0.8,
            dry_run=True,
        )
        assert cfg.enabled is False
        assert cfg.priority == pytest.approx(0.9)
        assert cfg.max_nodes_per_cycle == 50
        assert cfg.confidence_threshold == pytest.approx(0.8)
        assert cfg.dry_run is True

    def test_agent_config_enabled_default(self):
        """AgentConfig.enabled defaults to True."""
        cfg = AgentConfig()
        assert cfg.enabled is True

    def test_agent_config_dry_run_default(self):
        """AgentConfig.dry_run defaults to False."""
        cfg = AgentConfig()
        assert cfg.dry_run is False


class TestSwarmConfig:
    """Tests for the [`SwarmConfig`](memograph/swarm/config.py:18) dataclass."""

    def test_default_config(self):
        """SwarmConfig defaults: cycle_interval=3600, alpha=1.0, beta=2.0."""
        cfg = SwarmConfig()
        assert cfg.cycle_interval_seconds == pytest.approx(3600.0)
        assert cfg.alpha == pytest.approx(1.0)
        assert cfg.beta == pytest.approx(2.0)
        assert cfg.dry_run is False
        assert cfg.require_confirmation is False
        assert cfg.pheromone_evaporation_rate == pytest.approx(0.05)
        assert cfg.max_concurrent_agents == 2

    def test_summarizer_disabled_by_default(self):
        """SwarmConfig().summarizer.enabled == False (LLM-gated agent)."""
        cfg = SwarmConfig()
        assert cfg.summarizer.enabled is False

    def test_all_other_agents_enabled_by_default(self):
        """Tagger, linker, gap, and salience agents are enabled by default."""
        cfg = SwarmConfig()
        assert cfg.tagger.enabled is True
        assert cfg.linker.enabled is True
        assert cfg.gap.enabled is True
        assert cfg.salience.enabled is True

    def test_dry_run_flag(self):
        """SwarmConfig(dry_run=True).dry_run == True."""
        cfg = SwarmConfig(dry_run=True)
        assert cfg.dry_run is True

    def test_custom_cycle_interval(self):
        """Cycle interval can be overridden."""
        cfg = SwarmConfig(cycle_interval_seconds=1800.0)
        assert cfg.cycle_interval_seconds == pytest.approx(1800.0)

    def test_pheromone_persist_path_default_none(self):
        """pheromone_persist_path defaults to None."""
        cfg = SwarmConfig()
        assert cfg.pheromone_persist_path is None

    def test_pheromone_persist_path_custom(self):
        """pheromone_persist_path can be set to a string path."""
        cfg = SwarmConfig(pheromone_persist_path="/tmp/pheromones.json")
        assert cfg.pheromone_persist_path == "/tmp/pheromones.json"

    def test_gap_agent_max_nodes_reduced(self):
        """Gap agent defaults to max_nodes_per_cycle=10 (smaller than default 20)."""
        cfg = SwarmConfig()
        assert cfg.gap.max_nodes_per_cycle == 10

    def test_tagger_linker_salience_max_nodes_default(self):
        """Tagger, linker, and salience agents default to max_nodes_per_cycle=20."""
        cfg = SwarmConfig()
        assert cfg.tagger.max_nodes_per_cycle == 20
        assert cfg.linker.max_nodes_per_cycle == 20
        assert cfg.salience.max_nodes_per_cycle == 20

    def test_max_salience_boost_default(self):
        """max_salience_boost defaults to 0.2."""
        cfg = SwarmConfig()
        assert cfg.max_salience_boost == pytest.approx(0.2)

    def test_max_tags_per_cycle_default(self):
        """max_tags_per_cycle defaults to 5."""
        cfg = SwarmConfig()
        assert cfg.max_tags_per_cycle == 5

    def test_per_agent_configs_are_independent_instances(self):
        """Each SwarmConfig instance gets fresh per-agent AgentConfig instances."""
        cfg1 = SwarmConfig()
        cfg2 = SwarmConfig()
        cfg1.tagger.priority = 0.99
        # cfg2 should be unaffected
        assert cfg2.tagger.priority == pytest.approx(0.5)
