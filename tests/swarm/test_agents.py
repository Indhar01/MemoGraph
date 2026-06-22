"""Tests for the five concrete swarm agents (tagger, linker, gap, salience, summarizer)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memograph.swarm.agent_base import SwarmCycleReport
from memograph.swarm.config import AgentConfig, SwarmConfig
from memograph.swarm.pheromone import PheromoneMap


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kernel(tmp_path):
    """Minimal kernel with two test memories ingested."""
    from memograph.core.kernel import MemoryKernel

    k = MemoryKernel(vault_path=str(tmp_path / "vault"))
    k.remember("Python Tips", "Use list comprehensions for speed.", tags=["python"])
    k.remember(
        "Machine Learning", "Neural networks learn from data.", tags=["ai", "ml"]
    )
    k.ingest()
    return k


@pytest.fixture
def pheromone():
    return PheromoneMap()


@pytest.fixture
def dry_config():
    return SwarmConfig(dry_run=True)


def fresh_report():
    return SwarmCycleReport(cycle_id=1)


# ---------------------------------------------------------------------------
# TestTaggerAgent
# ---------------------------------------------------------------------------


class TestTaggerAgent:
    """Tests for [`TaggerAgent`](memograph/swarm/agents/tagger_agent.py:15)."""

    @pytest.mark.asyncio
    async def test_disabled_agent_returns_report_unchanged(
        self, kernel, pheromone, dry_config
    ):
        """When enabled=False, run_cycle returns the report without modifications."""
        from memograph.swarm.agents.tagger_agent import TaggerAgent

        cfg = AgentConfig(enabled=False)
        agent = TaggerAgent(kernel, pheromone, dry_config, cfg)
        report = fresh_report()
        result = await agent.run_cycle(report)
        assert result is report
        assert result.actions == []

    @pytest.mark.asyncio
    async def test_no_suggestions_creates_skip_action(
        self, kernel, pheromone, dry_config
    ):
        """When AutoTagger returns no suggestions, a skip action is created per node."""
        from memograph.swarm.agents.tagger_agent import TaggerAgent

        mock_tagger = AsyncMock()
        mock_tagger.suggest_tags = AsyncMock(return_value=[])

        with patch("memograph.ai.auto_tagger.AutoTagger", return_value=mock_tagger):
            agent = TaggerAgent(kernel, pheromone, dry_config, dry_config.tagger)
            report = fresh_report()
            result = await agent.run_cycle(report)

        skip_actions = [a for a in result.actions if a.action_type == "skip"]
        assert len(skip_actions) > 0

    @pytest.mark.asyncio
    async def test_suggestions_create_add_tags_action_dry_run(
        self, kernel, pheromone, dry_config
    ):
        """High-confidence suggestions produce an add_tags action (dry_run=True means applied=False)."""
        from memograph.swarm.agents.tagger_agent import TaggerAgent

        mock_suggestion = MagicMock()
        mock_suggestion.tag = "deep-learning"
        mock_suggestion.confidence = 0.9

        mock_tagger = AsyncMock()
        mock_tagger.suggest_tags = AsyncMock(return_value=[mock_suggestion])

        with patch("memograph.ai.auto_tagger.AutoTagger", return_value=mock_tagger):
            agent = TaggerAgent(kernel, pheromone, dry_config, dry_config.tagger)
            report = fresh_report()
            result = await agent.run_cycle(report)

        tag_actions = [a for a in result.actions if a.action_type == "add_tags"]
        assert len(tag_actions) > 0
        # dry_run=True means applied=False
        for a in tag_actions:
            assert a.applied is False
            assert a.dry_run is True

    @pytest.mark.asyncio
    async def test_pheromone_deposited_on_tagged_node(
        self, kernel, pheromone, dry_config
    ):
        """After a successful tag action, pheromone is deposited on the node."""
        from memograph.swarm.agents.tagger_agent import TaggerAgent

        mock_suggestion = MagicMock()
        mock_suggestion.tag = "tutorial"
        mock_suggestion.confidence = 0.85

        mock_tagger = AsyncMock()
        mock_tagger.suggest_tags = AsyncMock(return_value=[mock_suggestion])

        with patch("memograph.ai.auto_tagger.AutoTagger", return_value=mock_tagger):
            agent = TaggerAgent(kernel, pheromone, dry_config, dry_config.tagger)
            await agent.run_cycle(fresh_report())

        assert pheromone.node_count() > 0

    @pytest.mark.asyncio
    async def test_ai_failure_falls_back_to_heuristic(
        self, kernel, pheromone, dry_config
    ):
        """If AutoTagger raises, the agent falls back to heuristic tagging (no error)."""
        from memograph.swarm.agents.tagger_agent import TaggerAgent

        mock_tagger = AsyncMock()
        mock_tagger.suggest_tags = AsyncMock(side_effect=RuntimeError("API down"))

        with patch("memograph.ai.auto_tagger.AutoTagger", return_value=mock_tagger):
            agent = TaggerAgent(kernel, pheromone, dry_config, dry_config.tagger)
            report = fresh_report()
            result = await agent.run_cycle(report)

        # Should gracefully fall back, not produce errors
        assert len(result.errors) == 0
        # Should still produce actions (heuristic tags or skips)
        assert len(result.actions) > 0


# ---------------------------------------------------------------------------
# TestLinkerAgent
# ---------------------------------------------------------------------------


class TestLinkerAgent:
    """Tests for [`LinkerAgent`](memograph/swarm/agents/linker_agent.py:15)."""

    @pytest.mark.asyncio
    async def test_disabled_returns_report_unchanged(
        self, kernel, pheromone, dry_config
    ):
        """When enabled=False, run_cycle returns the report without modifications."""
        from memograph.swarm.agents.linker_agent import LinkerAgent

        cfg = AgentConfig(enabled=False)
        agent = LinkerAgent(kernel, pheromone, dry_config, cfg)
        report = fresh_report()
        result = await agent.run_cycle(report)
        assert result is report
        assert result.actions == []

    @pytest.mark.asyncio
    async def test_links_produce_add_links_action(self, kernel, pheromone, dry_config):
        """High-confidence link suggestions produce add_links actions."""
        from memograph.swarm.agents.linker_agent import LinkerAgent

        mock_link = MagicMock()
        mock_link.target_id = "machine-learning"
        mock_link.target_title = "Machine Learning"
        mock_link.confidence = 0.9

        mock_suggester = AsyncMock()
        mock_suggester.suggest_links = AsyncMock(return_value=[mock_link])

        with patch(
            "memograph.ai.link_suggester.LinkSuggester", return_value=mock_suggester
        ):
            agent = LinkerAgent(kernel, pheromone, dry_config, dry_config.linker)
            report = fresh_report()
            result = await agent.run_cycle(report)

        link_actions = [a for a in result.actions if a.action_type == "add_links"]
        assert len(link_actions) > 0
        for a in link_actions:
            assert a.dry_run is True
            assert a.applied is False

    @pytest.mark.asyncio
    async def test_no_links_creates_skip_action(self, kernel, pheromone, dry_config):
        """When LinkSuggester returns no suggestions, a skip action is created."""
        from memograph.swarm.agents.linker_agent import LinkerAgent

        mock_suggester = AsyncMock()
        mock_suggester.suggest_links = AsyncMock(return_value=[])

        with patch(
            "memograph.ai.link_suggester.LinkSuggester", return_value=mock_suggester
        ):
            agent = LinkerAgent(kernel, pheromone, dry_config, dry_config.linker)
            report = fresh_report()
            result = await agent.run_cycle(report)

        skip_actions = [a for a in result.actions if a.action_type == "skip"]
        assert len(skip_actions) > 0


# ---------------------------------------------------------------------------
# TestGapAgent
# ---------------------------------------------------------------------------


class TestGapAgent:
    """Tests for [`GapAgent`](memograph/swarm/agents/gap_agent.py:17)."""

    @pytest.mark.asyncio
    async def test_disabled_returns_report_unchanged(
        self, kernel, pheromone, dry_config
    ):
        """When enabled=False, run_cycle returns the report without modifications."""
        from memograph.swarm.agents.gap_agent import GapAgent

        cfg = AgentConfig(enabled=False)
        agent = GapAgent(kernel, pheromone, dry_config, cfg)
        report = fresh_report()
        result = await agent.run_cycle(report)
        assert result is report
        assert result.actions == []

    @pytest.mark.asyncio
    async def test_no_gaps_returns_report_unchanged(
        self, kernel, pheromone, dry_config
    ):
        """When GapDetector returns no gaps, the report is not modified."""
        from memograph.swarm.agents.gap_agent import GapAgent

        mock_detector = AsyncMock()
        mock_detector.detect_gaps = AsyncMock(return_value=[])

        with patch(
            "memograph.swarm.agents.gap_agent.GapDetector", return_value=mock_detector
        ):
            agent = GapAgent(kernel, pheromone, dry_config, dry_config.gap)
            report = fresh_report()
            result = await agent.run_cycle(report)

        assert result.actions == []

    @pytest.mark.asyncio
    async def test_missing_topic_gap_creates_flag_gap_action(
        self, kernel, pheromone, dry_config
    ):
        """A missing_topic gap creates a flag_gap action."""
        from memograph.swarm.agents.gap_agent import GapAgent

        mock_gap = MagicMock()
        mock_gap.gap_type = "missing_topic"
        mock_gap.title = "Missing note about 'asyncio'"
        mock_gap.description = "Topic frequently mentioned but no note exists."
        mock_gap.severity = 0.8
        mock_gap.related_notes = ["python-tips"]

        mock_detector = AsyncMock()
        mock_detector.detect_gaps = AsyncMock(return_value=[mock_gap])

        with patch(
            "memograph.swarm.agents.gap_agent.GapDetector", return_value=mock_detector
        ):
            agent = GapAgent(kernel, pheromone, dry_config, dry_config.gap)
            report = fresh_report()
            result = await agent.run_cycle(report)

        flag_actions = [a for a in result.actions if a.action_type == "flag_gap"]
        assert len(flag_actions) == 1
        assert flag_actions[0].dry_run is True
        assert flag_actions[0].applied is False

    @pytest.mark.asyncio
    async def test_non_missing_topic_gaps_are_ignored(
        self, kernel, pheromone, dry_config
    ):
        """Gaps with gap_type != 'missing_topic' are skipped."""
        from memograph.swarm.agents.gap_agent import GapAgent

        mock_gap = MagicMock()
        mock_gap.gap_type = "isolated_note"
        mock_gap.title = "Some isolated note"
        mock_gap.description = "desc"
        mock_gap.severity = 0.7
        mock_gap.related_notes = []

        mock_detector = AsyncMock()
        mock_detector.detect_gaps = AsyncMock(return_value=[mock_gap])

        with patch(
            "memograph.swarm.agents.gap_agent.GapDetector", return_value=mock_detector
        ):
            agent = GapAgent(kernel, pheromone, dry_config, dry_config.gap)
            report = fresh_report()
            result = await agent.run_cycle(report)

        assert result.actions == []

    @pytest.mark.asyncio
    async def test_detection_exception_adds_error(self, kernel, pheromone, dry_config):
        """If GapDetector.detect_gaps() raises, the error is captured in report.errors."""
        from memograph.swarm.agents.gap_agent import GapAgent

        mock_detector = AsyncMock()
        mock_detector.detect_gaps = AsyncMock(
            side_effect=RuntimeError("service unavailable")
        )

        with patch(
            "memograph.swarm.agents.gap_agent.GapDetector", return_value=mock_detector
        ):
            agent = GapAgent(kernel, pheromone, dry_config, dry_config.gap)
            report = fresh_report()
            result = await agent.run_cycle(report)

        assert len(result.errors) > 0


class TestSalienceAgent:
    """Tests for [`SalienceAgent`](memograph/swarm/agents/salience_agent.py:15)."""

    @pytest.mark.asyncio
    async def test_disabled_returns_report_unchanged(
        self, kernel, pheromone, dry_config
    ):
        """When enabled=False, run_cycle returns the report without modifications."""
        from memograph.swarm.agents.salience_agent import SalienceAgent

        cfg = AgentConfig(enabled=False)
        agent = SalienceAgent(kernel, pheromone, dry_config, cfg)
        report = fresh_report()
        result = await agent.run_cycle(report)
        assert result is report
        assert result.actions == []

    @pytest.mark.asyncio
    async def test_empty_graph_returns_report_unchanged(
        self, tmp_path, pheromone, dry_config
    ):
        """SalienceAgent on an empty graph returns the report unchanged."""
        from memograph.core.kernel import MemoryKernel
        from memograph.swarm.agents.salience_agent import SalienceAgent

        empty_kernel = MemoryKernel(vault_path=str(tmp_path / "empty"))
        empty_kernel.ingest()
        agent = SalienceAgent(empty_kernel, pheromone, dry_config, dry_config.salience)
        report = fresh_report()
        result = await agent.run_cycle(report)
        assert result.actions == []

    @pytest.mark.asyncio
    async def test_all_actions_are_valid_types(self, kernel, pheromone, dry_config):
        """All actions produced are either 'boost_salience' or 'skip'."""
        from memograph.swarm.agents.salience_agent import SalienceAgent

        agent = SalienceAgent(kernel, pheromone, dry_config, dry_config.salience)
        result = await agent.run_cycle(fresh_report())
        for a in result.actions:
            assert a.action_type in ("boost_salience", "skip")

    @pytest.mark.asyncio
    async def test_high_access_node_gets_boost_action(
        self, tmp_path, pheromone, dry_config
    ):
        """A node with high access_count and low salience gets a boost_salience action."""
        from memograph.core.kernel import MemoryKernel
        from memograph.swarm.agents.salience_agent import SalienceAgent

        k = MemoryKernel(vault_path=str(tmp_path / "vault"))
        k.remember("Hot Topic", "Very popular content here.", tags=["hot"])
        k.ingest()
        node = list(k.graph._nodes.values())[0]
        node.access_count = 50
        node.salience = 0.05
        agent = SalienceAgent(k, pheromone, dry_config, dry_config.salience)
        result = await agent.run_cycle(fresh_report())
        boost_actions = [a for a in result.actions if a.action_type == "boost_salience"]
        assert len(boost_actions) > 0
        assert boost_actions[0].dry_run is True
        assert boost_actions[0].applied is False


class TestSummarizerAgent:
    """Tests for [`SummarizerAgent`](memograph/swarm/agents/summarizer_agent.py:23)."""

    @pytest.mark.asyncio
    async def test_disabled_by_default(self, kernel, pheromone, dry_config):
        """SummarizerAgent disabled by default; run_cycle returns report unchanged."""
        from memograph.swarm.agents.summarizer_agent import SummarizerAgent

        agent = SummarizerAgent(kernel, pheromone, dry_config, dry_config.summarizer)
        result = await agent.run_cycle(fresh_report())
        assert result.actions == []

    @pytest.mark.asyncio
    async def test_short_content_skip(self, tmp_path, pheromone):
        """Nodes with < 200 words get content_too_short skip action."""
        from memograph.core.kernel import MemoryKernel
        from memograph.swarm.agents.summarizer_agent import SummarizerAgent

        k = MemoryKernel(vault_path=str(tmp_path / "vault"))
        k.remember("Short", "A short note.", tags=[])
        k.ingest()
        cfg = SwarmConfig(dry_run=True)
        cfg.summarizer.enabled = True
        agent = SummarizerAgent(k, pheromone, cfg, cfg.summarizer)
        result = await agent.run_cycle(fresh_report())
        skip_actions = [a for a in result.actions if a.action_type == "skip"]
        assert len(skip_actions) > 0
        assert any(a.payload.get("reason") == "content_too_short" for a in skip_actions)

    @pytest.mark.asyncio
    async def test_already_summarised_node_skipped(self, tmp_path, pheromone):
        """Node with summary marker already in content gets already_summarised skip."""
        from memograph.core.kernel import MemoryKernel
        from memograph.swarm.agents.summarizer_agent import (
            SummarizerAgent,
            _SUMMARY_MARKER,
        )

        k = MemoryKernel(vault_path=str(tmp_path / "vault"))
        long_content = ("word " * 210) + _SUMMARY_MARKER
        k.remember("Already Done", long_content, tags=[])
        k.ingest()
        cfg = SwarmConfig(dry_run=True)
        cfg.summarizer.enabled = True
        agent = SummarizerAgent(k, pheromone, cfg, cfg.summarizer)
        result = await agent.run_cycle(fresh_report())
        assert any(
            a.action_type == "skip" and a.payload.get("reason") == "already_summarised"
            for a in result.actions
        )

    @pytest.mark.asyncio
    async def test_long_content_extractive_fallback(self, tmp_path, pheromone):
        """Long content without LLM uses extractive fallback (produces summarize action)."""
        from memograph.core.kernel import MemoryKernel
        from memograph.swarm.agents.summarizer_agent import SummarizerAgent

        k = MemoryKernel(vault_path=str(tmp_path / "vault"))
        long_content = "Python is a great language. " * 60
        k.remember("Long Note", long_content, tags=[])
        k.ingest()
        cfg = SwarmConfig(dry_run=True)
        cfg.summarizer.enabled = True
        agent = SummarizerAgent(k, pheromone, cfg, cfg.summarizer)
        result = await agent.run_cycle(fresh_report())
        # Should produce at least one action
        assert len(result.actions) > 0
        non_skip = [a for a in result.actions if a.action_type != "skip"]
        assert len(non_skip) > 0
        assert all(a.action_type == "summarize" for a in non_skip)
        assert all(a.dry_run is True for a in non_skip)
