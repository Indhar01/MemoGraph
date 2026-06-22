"""Tests for PheromoneMap and PheromoneDeposit (memograph/swarm/pheromone.py)."""

from datetime import datetime, timedelta, timezone

import pytest

from memograph.swarm.pheromone import PheromoneDeposit, PheromoneMap


# ---------------------------------------------------------------------------
# TestPheromoneDeposit
# ---------------------------------------------------------------------------


class TestPheromoneDeposit:
    """Unit tests for the [`PheromoneDeposit`](memograph/swarm/pheromone.py:25) dataclass."""

    def test_deposit_creation(self):
        """create a PheromoneDeposit, verify all fields."""
        dep = PheromoneDeposit(
            node_id="node-abc",
            agent_type="tagger",
            signal_type="tagged",
            strength=0.75,
            timestamp="2024-01-01T00:00:00+00:00",
            payload={"tags_added": ["python"]},
        )
        assert dep.node_id == "node-abc"
        assert dep.agent_type == "tagger"
        assert dep.signal_type == "tagged"
        assert dep.strength == 0.75
        assert dep.timestamp == "2024-01-01T00:00:00+00:00"
        assert dep.payload == {"tags_added": ["python"]}

    def test_deposit_default_payload(self):
        """PheromoneDeposit payload defaults to empty dict."""
        dep = PheromoneDeposit(
            node_id="node-xyz",
            agent_type="linker",
            signal_type="linked",
            strength=0.5,
            timestamp="2024-01-01T00:00:00+00:00",
        )
        assert dep.payload == {}

    def test_deposit_strength_clamped(self):
        """Strength out of range [0, 1] is clamped when deposited via PheromoneMap.deposit()."""
        pmap = PheromoneMap()

        dep_high = pmap.deposit("n1", "tagger", "tagged", strength=2.5)
        dep_low = pmap.deposit("n2", "tagger", "tagged", strength=-1.0)
        dep_exact = pmap.deposit("n3", "tagger", "tagged", strength=0.9)

        assert dep_high.strength == 1.0, "Strength > 1.0 should be clamped to 1.0"
        assert dep_low.strength == 0.0, "Negative strength should be clamped to 0.0"
        assert dep_exact.strength == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# TestPheromoneMap
# ---------------------------------------------------------------------------


class TestPheromoneMap:
    """Unit tests for the [`PheromoneMap`](memograph/swarm/pheromone.py:36) class."""

    # ------------------------------------------------------------------
    # Basic deposit / read
    # ------------------------------------------------------------------

    def test_deposit_and_read(self):
        """Deposit a pheromone and read it back from the map."""
        pmap = PheromoneMap()
        dep = pmap.deposit("node-1", "tagger", "tagged", strength=0.8)

        deposits = pmap.get_deposits("node-1")
        assert len(deposits) == 1
        assert deposits[0].node_id == "node-1"
        assert deposits[0].agent_type == "tagger"
        assert deposits[0].signal_type == "tagged"
        assert deposits[0].strength == pytest.approx(0.8)
        assert dep is deposits[0]

    def test_get_deposits_unknown_node_returns_empty_list(self):
        """get_deposits for an unregistered node returns []."""
        pmap = PheromoneMap()
        assert pmap.get_deposits("nonexistent") == []

    def test_get_total_strength(self):
        """Sum of multiple deposits on same node, capped at 1.0."""
        pmap = PheromoneMap()
        pmap.deposit("node-x", "tagger", "tagged", strength=0.4)
        pmap.deposit("node-x", "linker", "linked", strength=0.3)

        total = pmap.get_total_strength("node-x")
        assert total == pytest.approx(0.7)

    def test_get_total_strength_capped(self):
        """Total strength from multiple deposits is capped at 1.0."""
        pmap = PheromoneMap()
        pmap.deposit("node-cap", "tagger", "tagged", strength=0.8)
        pmap.deposit("node-cap", "linker", "linked", strength=0.8)

        total = pmap.get_total_strength("node-cap")
        assert total == pytest.approx(1.0), "Total strength should not exceed 1.0"

    def test_get_total_strength_no_deposits(self):
        """Node with no pheromone returns 0.0."""
        pmap = PheromoneMap()
        assert pmap.get_total_strength("node-empty") == 0.0

    def test_get_agent_strength(self):
        """Filter pheromone strength by agent_type."""
        pmap = PheromoneMap()
        pmap.deposit("node-y", "tagger", "tagged", strength=0.6)
        pmap.deposit("node-y", "linker", "linked", strength=0.3)

        tagger_strength = pmap.get_agent_strength("node-y", "tagger")
        linker_strength = pmap.get_agent_strength("node-y", "linker")
        gap_strength = pmap.get_agent_strength("node-y", "gap")  # none deposited

        assert tagger_strength == pytest.approx(0.6)
        assert linker_strength == pytest.approx(0.3)
        assert gap_strength == 0.0

    # ------------------------------------------------------------------
    # Evaporation
    # ------------------------------------------------------------------

    def test_evaporate_reduces_strength(self):
        """After evaporation with rate=0.5, strength should halve."""
        pmap = PheromoneMap()
        pmap.deposit("node-ev", "tagger", "tagged", strength=0.8)

        pmap.evaporate(rate=0.5)

        deposits = pmap.get_deposits("node-ev")
        assert len(deposits) == 1
        assert deposits[0].strength == pytest.approx(0.4, abs=1e-6)

    def test_evaporate_prunes_weak_deposits(self):
        """Deposits that decay below the prune threshold (0.001) are removed."""
        pmap = PheromoneMap()
        # Deposit very small strength so it drops below threshold on first evaporation
        pmap.deposit("node-prune", "tagger", "tagged", strength=0.0005)

        pruned = pmap.evaporate(rate=0.5)

        assert pruned == 1, "Weak deposit should be pruned"
        assert pmap.get_deposits("node-prune") == []
        assert "node-prune" not in pmap.all_node_ids()

    def test_evaporate_keeps_deposits_above_threshold(self):
        """Deposits above the prune threshold survive evaporation."""
        pmap = PheromoneMap()
        pmap.deposit("node-keep", "tagger", "tagged", strength=0.9)

        pruned = pmap.evaporate(rate=0.1)

        assert pruned == 0
        deposits = pmap.get_deposits("node-keep")
        assert len(deposits) == 1

    def test_was_visited_recently_true(self):
        """Returns True if deposit exists within the time window."""
        pmap = PheromoneMap()
        pmap.deposit("node-recent", "tagger", "tagged", strength=0.9)
        assert (
            pmap.was_visited_recently("node-recent", "tagger", within_seconds=3600.0)
            is True
        )

    def test_was_visited_recently_false_no_deposit(self):
        """Returns False if no deposit exists for that agent type."""
        pmap = PheromoneMap()
        pmap.deposit("node-other", "linker", "linked", strength=0.8)
        assert (
            pmap.was_visited_recently("node-other", "tagger", within_seconds=3600.0)
            is False
        )

    def test_was_visited_recently_false_stale(self):
        """Returns False when the deposit is outside the time window."""
        pmap = PheromoneMap()
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        dep = PheromoneDeposit(
            node_id="node-stale",
            agent_type="tagger",
            signal_type="tagged",
            strength=0.8,
            timestamp=old_ts,
        )
        pmap._deposits["node-stale"].append(dep)
        assert (
            pmap.was_visited_recently("node-stale", "tagger", within_seconds=3600.0)
            is False
        )

    def test_aco_score_unvisited_node(self):
        """Node with no pheromone gets a high ACO score."""
        pmap = PheromoneMap()
        # score = (1 - 0)^1.0 * 0.8^2.0 = 1.0 * 0.64 = 0.64
        score = pmap.aco_score("node-fresh", heuristic=0.8, alpha=1.0, beta=2.0)
        assert score == pytest.approx(0.64, abs=1e-6)

    def test_aco_score_visited_node(self):
        """Node with high pheromone gets lower ACO score than an unvisited node."""
        pmap = PheromoneMap()
        pmap.deposit("node-visited", "tagger", "tagged", strength=0.9)
        score_visited = pmap.aco_score(
            "node-visited", heuristic=0.8, alpha=1.0, beta=2.0
        )
        score_fresh = pmap.aco_score("node-fresh", heuristic=0.8, alpha=1.0, beta=2.0)
        assert score_visited < score_fresh

    def test_aco_score_zero_heuristic(self):
        """Node with heuristic=0 yields ACO score of 0."""
        pmap = PheromoneMap()
        score = pmap.aco_score("node-z", heuristic=0.0, alpha=1.0, beta=2.0)
        assert score == pytest.approx(0.0)

    def test_rank_nodes(self):
        """rank_nodes returns nodes sorted by ACO score descending."""
        pmap = PheromoneMap()
        pmap.deposit("node-A", "tagger", "tagged", strength=0.9)
        node_ids = ["node-A", "node-B", "node-C"]
        heuristics = {"node-A": 0.8, "node-B": 0.8, "node-C": 0.8}
        ranked = pmap.rank_nodes(node_ids, heuristics, alpha=1.0, beta=2.0)
        assert len(ranked) == 3
        ids_in_order = [nid for nid, _ in ranked]
        assert ids_in_order[-1] == "node-A"
        scores = [score for _, score in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_rank_nodes_top_k(self):
        """rank_nodes top_k limits the output length."""
        pmap = PheromoneMap()
        node_ids = [f"node-{i}" for i in range(10)]
        heuristics = {nid: 0.5 for nid in node_ids}
        ranked = pmap.rank_nodes(node_ids, heuristics, top_k=3)
        assert len(ranked) == 3

    def test_save_and_load(self, tmp_path):
        """Save to tmp file, load back, verify deposits preserved."""
        pmap = PheromoneMap()
        pmap.deposit(
            "node-p1",
            "tagger",
            "tagged",
            strength=0.7,
            payload={"tags_added": ["python"]},
        )
        pmap.deposit("node-p2", "linker", "linked", strength=0.5)
        pmap.evaporate(rate=0.1)

        save_path = tmp_path / "pheromones.json"
        pmap.save(save_path)
        assert save_path.exists()

        pmap2 = PheromoneMap()
        pmap2.load(save_path)

        assert pmap2.node_count() == 2
        assert pmap2._evaporation_count == 1
        deps1 = pmap2.get_deposits("node-p1")
        assert len(deps1) == 1
        assert deps1[0].agent_type == "tagger"
        assert deps1[0].payload == {"tags_added": ["python"]}

    def test_save_no_path_does_not_raise(self):
        """save() with no persist_path configured silently skips."""
        pmap = PheromoneMap()
        pmap.deposit("node-x", "tagger", "tagged", strength=0.5)
        pmap.save()  # no path — should not raise

    def test_load_missing_file_does_not_raise(self, tmp_path):
        """load() with a nonexistent file does not raise."""
        pmap = PheromoneMap()
        pmap.load(tmp_path / "missing.json")

    def test_persist_path_loads_on_init(self, tmp_path):
        """PheromoneMap auto-loads from persist_path if file already exists."""
        save_path = tmp_path / "pheromones.json"
        pmap1 = PheromoneMap()
        pmap1.deposit("auto-node", "salience", "salience_boosted", strength=0.6)
        pmap1.save(save_path)

        pmap2 = PheromoneMap(persist_path=save_path)
        assert pmap2.node_count() == 1
        assert pmap2.get_total_strength("auto-node") == pytest.approx(0.6, abs=1e-3)

    def test_get_summary(self):
        """summary() returns dict with expected keys and correct counts."""
        pmap = PheromoneMap()
        pmap.deposit("n1", "tagger", "tagged", strength=0.8)
        pmap.deposit("n2", "linker", "linked", strength=0.5)
        pmap.deposit("n2", "gap", "gap_found", strength=0.3)

        s = pmap.summary()

        assert "node_count" in s
        assert "deposit_count" in s
        assert "evaporation_cycles" in s
        assert "top_nodes" in s
        assert s["node_count"] == 2
        assert s["deposit_count"] == 3
        assert s["evaporation_cycles"] == 0
        assert isinstance(s["top_nodes"], list)
