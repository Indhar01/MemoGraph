"""Capture-mode filter shared by Tier-A (Claude Code hook) and Tier-B (MCP).

The "capture mode" is a single user-facing dial — ``low`` / ``mid`` / ``high`` —
that controls how aggressively conversation turns get persisted to the vault.

It is read from the ``MEMOGRAPH_CAPTURE_MODE`` env var at server startup and
can be flipped at runtime via the ``configure_capture_mode`` MCP tool. Both
the unified ``auto_hook_turn`` MCP tool (callable by any MCP client) and the
Claude Code ``Stop`` hook script delegate the save/no-save decision to
``should_save`` so behavior stays identical regardless of trigger.

Modes:

- ``low``    — search-only. Never writes to the vault. Useful when a user
  wants context recall but is wary of vault growth (e.g. exploring a new
  project, working with sensitive content).
- ``mid``    — default. Saves substantive turns and filters obvious noise:
  short user queries, tool-result-only AI responses, and combined
  exchanges below a minimum length threshold.
- ``high``   — save every substantive turn verbatim. Only the 10-char user
  query floor still applies. Highest fidelity, largest vault.

The decision is intentionally heuristic, not LLM-judged: an LLM call here
would defeat the purpose of a deterministic capture path.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


CaptureMode = Literal["low", "mid", "high"]
VALID_MODES: tuple[CaptureMode, ...] = ("low", "mid", "high")
DEFAULT_MODE: CaptureMode = "mid"

MIN_USER_QUERY_LEN = 10
MIN_AI_RESPONSE_LEN = 20
MIN_COMBINED_LEN_MID = 80

_TOOL_RESULT_ECHO_RE = re.compile(
    r"^\s*(```|<tool_result|<tool_use_result|\{|\[)", re.MULTILINE
)

_TRIVIAL_AI_PHRASES = frozenset(
    {
        "done.",
        "ok.",
        "okay.",
        "sure.",
        "got it.",
        "understood.",
        "sounds good.",
    }
)


@dataclass(frozen=True)
class CaptureDecision:
    """Result of a capture decision.

    Attributes:
        save: Whether this exchange should be written to the vault.
        salience: Recommended salience (0.0–1.0); only meaningful when save is True.
        tags: Suggested tags to attach (caller may extend with its own).
        reason: Short machine-readable code for why we chose this. Useful for
            telemetry / debugging when users ask "why didn't this save?".
    """

    save: bool
    salience: float
    tags: tuple[str, ...]
    reason: str


def normalize_mode(value: str | None) -> CaptureMode:
    """Coerce an arbitrary input into a valid CaptureMode, defaulting to DEFAULT_MODE.

    Unknown / empty / None values fall back to the default so a typo in
    ``MEMOGRAPH_CAPTURE_MODE`` cannot disable the system silently.
    """
    if not value:
        return DEFAULT_MODE
    candidate = value.strip().lower()
    if candidate in VALID_MODES:
        return candidate  # type: ignore[return-value]
    logger.warning(
        "Unknown capture mode %r; falling back to %r. Valid modes: %s",
        value,
        DEFAULT_MODE,
        ", ".join(VALID_MODES),
    )
    return DEFAULT_MODE


def _looks_like_tool_result_echo(ai_response: str) -> bool:
    """Heuristic: AI replies that are mostly raw tool output, not synthesis.

    A tool-result echo offers little durable value — the relevant info is
    already in the user's tool history. We skip these in ``mid``.
    """
    stripped = ai_response.strip()
    if not stripped:
        return True
    if stripped.lower() in _TRIVIAL_AI_PHRASES:
        return True
    # If >70% of lines look like code-fence / JSON / XML-result markers,
    # treat as echo. Coarse but cheap.
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if not lines:
        return True
    marker_lines = sum(1 for ln in lines if _TOOL_RESULT_ECHO_RE.match(ln))
    return marker_lines / max(len(lines), 1) > 0.7


def should_save(
    user_query: str,
    ai_response: str,
    mode: CaptureMode | str | None = None,
    *,
    sources_cited: bool = False,
) -> CaptureDecision:
    """Decide whether to persist a turn, and at what salience.

    Args:
        user_query: The user's message for this turn (verbatim).
        ai_response: The assistant's reply text.
        mode: Capture mode. String inputs are coerced; unknown values fall
            back to ``DEFAULT_MODE``.
        sources_cited: True if the AI used vault sources in its reply (boosts
            salience because the turn ties to existing graph state).

    Returns:
        ``CaptureDecision`` describing the verdict.
    """
    resolved_mode = normalize_mode(
        mode if isinstance(mode, str) or mode is None else None
    )
    user_query = (user_query or "").strip()
    ai_response = (ai_response or "").strip()

    base_tags: tuple[str, ...] = ("conversation", "interaction")

    if resolved_mode == "low":
        return CaptureDecision(
            save=False,
            salience=0.0,
            tags=base_tags,
            reason="mode_low_search_only",
        )

    if len(user_query) < MIN_USER_QUERY_LEN:
        return CaptureDecision(
            save=False,
            salience=0.0,
            tags=base_tags,
            reason="user_query_too_short",
        )

    if resolved_mode == "high":
        # High mode: save everything past the query-length floor.
        salience = 0.75 if sources_cited else 0.65
        return CaptureDecision(
            save=True,
            salience=salience,
            tags=base_tags + ("capture-high",),
            reason="mode_high_save_all",
        )

    # mid mode: filter the obvious noise.
    if len(ai_response) < MIN_AI_RESPONSE_LEN:
        return CaptureDecision(
            save=False,
            salience=0.0,
            tags=base_tags,
            reason="ai_response_too_short",
        )

    if len(user_query) + len(ai_response) < MIN_COMBINED_LEN_MID:
        return CaptureDecision(
            save=False,
            salience=0.0,
            tags=base_tags,
            reason="combined_too_short",
        )

    if _looks_like_tool_result_echo(ai_response):
        return CaptureDecision(
            save=False,
            salience=0.0,
            tags=base_tags,
            reason="ai_response_is_tool_echo",
        )

    salience = 0.7 if sources_cited else 0.5
    return CaptureDecision(
        save=True,
        salience=salience,
        tags=base_tags + ("capture-mid",),
        reason="mode_mid_passed_filter",
    )
