"""Tests for the low/mid/high capture filter."""

import pytest

from memograph.mcp.capture_filter import (
    DEFAULT_MODE,
    VALID_MODES,
    normalize_mode,
    should_save,
)


SUBSTANTIVE_QUERY = (
    "What is the architectural difference between VaultGraph and VaultIndexer?"
)
SUBSTANTIVE_REPLY = (
    "VaultGraph is an in-memory adjacency structure with O(1) lookups by ID, tag, "
    "and type. VaultIndexer is the file watcher that re-parses changed files and "
    "feeds them into VaultGraph. Indexer owns the lifecycle; graph owns the shape."
)


class TestNormalizeMode:
    def test_valid_modes_pass_through(self) -> None:
        for mode in VALID_MODES:
            assert normalize_mode(mode) == mode

    def test_case_and_whitespace_normalized(self) -> None:
        assert normalize_mode("  HIGH ") == "high"
        assert normalize_mode("Mid") == "mid"

    def test_unknown_falls_back_to_default(self) -> None:
        assert normalize_mode("aggressive") == DEFAULT_MODE
        assert normalize_mode("") == DEFAULT_MODE
        assert normalize_mode(None) == DEFAULT_MODE

    def test_default_is_mid(self) -> None:
        assert DEFAULT_MODE == "mid"


class TestLowMode:
    def test_never_saves_even_for_substantive_turn(self) -> None:
        decision = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, "low")
        assert decision.save is False
        assert decision.reason == "mode_low_search_only"


class TestHighMode:
    def test_saves_substantive_turn(self) -> None:
        decision = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, "high")
        assert decision.save is True
        assert "capture-high" in decision.tags

    def test_saves_short_ai_reply(self) -> None:
        # High mode bypasses noise filtering — the only floor is query length.
        decision = should_save(SUBSTANTIVE_QUERY, "Yes.", "high")
        assert decision.save is True

    def test_skips_short_user_query(self) -> None:
        decision = should_save("ok", SUBSTANTIVE_REPLY, "high")
        assert decision.save is False
        assert decision.reason == "user_query_too_short"

    def test_sources_boost_salience(self) -> None:
        without = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, "high")
        with_sources = should_save(
            SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, "high", sources_cited=True
        )
        assert with_sources.salience > without.salience


class TestMidMode:
    def test_saves_substantive_turn(self) -> None:
        decision = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, "mid")
        assert decision.save is True
        assert "capture-mid" in decision.tags

    def test_skips_short_user_query(self) -> None:
        decision = should_save("ok", SUBSTANTIVE_REPLY, "mid")
        assert decision.save is False
        assert decision.reason == "user_query_too_short"

    def test_skips_trivial_ai_reply(self) -> None:
        decision = should_save(SUBSTANTIVE_QUERY, "Done.", "mid")
        assert decision.save is False

    def test_skips_tool_result_echo(self) -> None:
        echo = "\n".join(["```json", '{"result": "ok"}', "```"])
        decision = should_save(SUBSTANTIVE_QUERY, echo, "mid")
        assert decision.save is False
        assert decision.reason == "ai_response_is_tool_echo"

    def test_skips_below_combined_threshold(self) -> None:
        decision = should_save("Short but valid query", "Short but valid reply", "mid")
        assert decision.save is False
        assert decision.reason == "combined_too_short"

    def test_sources_cited_boost_salience(self) -> None:
        without = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, "mid")
        with_sources = should_save(
            SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, "mid", sources_cited=True
        )
        assert with_sources.salience > without.salience


class TestDefaultBehavior:
    def test_none_mode_uses_default(self) -> None:
        d1 = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, None)
        d2 = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, DEFAULT_MODE)
        assert d1.save == d2.save
        assert d1.reason == d2.reason

    def test_unknown_mode_uses_default(self) -> None:
        d_unknown = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, "turbo")
        d_default = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, DEFAULT_MODE)
        assert d_unknown.save == d_default.save


@pytest.mark.parametrize("mode", list(VALID_MODES))
def test_returns_immutable_decision(mode: str) -> None:
    decision = should_save(SUBSTANTIVE_QUERY, SUBSTANTIVE_REPLY, mode)
    with pytest.raises(Exception):
        decision.save = False  # type: ignore[misc]
