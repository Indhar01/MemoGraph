"""SummarizerAgent — swarm agent that appends auto-generated summaries to long nodes.

This agent is **disabled by default** (``AgentConfig(enabled=False)``) because it
requires an LLM client to be configured on the kernel.  Enable it by setting
``SwarmConfig.summarizer.enabled = True`` after attaching an LLM to the kernel.
"""

import logging

from memograph.swarm.agent_base import SwarmAction, SwarmAgent, SwarmCycleReport

logger = logging.getLogger("memograph.swarm.summarizer")

# Minimum word count before a node is eligible for summarisation
_MIN_WORDS_FOR_SUMMARY = 200

# Marker inserted at the top of the generated summary block so the agent
# can detect nodes that have already been summarised and avoid re-running.
_SUMMARY_MARKER = "<!-- swarm-summary -->"


class SummarizerAgent(SwarmAgent):
    """Swarm agent that generates and appends TL;DR summaries to long notes.

    Long notes (> ``_MIN_WORDS_FOR_SUMMARY`` words) that lack a summary section
    are selected by the ACO heuristic.  The agent uses the kernel's LLM client
    (accessed through ``kernel.organizer``) to produce a short summary, then
    appends it to the node content via
    :py:meth:`~memograph.core.kernel.MemoryKernel.update_many`.

    The heuristic favours nodes with:
    * High word count (long notes benefit most from summaries)
    * High access count (frequently read notes should be easy to skim)
    * No existing ``<!-- swarm-summary -->`` marker (not yet summarised)

    .. note::
        Disabled by default — requires ``SwarmConfig.summarizer.enabled = True``
        and a kernel with an LLM client (``kernel.llm_client`` or
        ``kernel.organizer``).

    Example:
        >>> config = SwarmConfig()
        >>> config.summarizer.enabled = True
        >>> agent = SummarizerAgent(kernel, pheromone, config, config.summarizer)
        >>> report = await agent.run_cycle(SwarmCycleReport(cycle_id=1))
        >>> print(f"Summarised {len(report.applied_actions)} nodes")
    """

    agent_type: str = "summarizer"

    async def run_cycle(self, report: SwarmCycleReport) -> SwarmCycleReport:
        """Execute one summarisation cycle.

        For each ACO-selected candidate node:
        1. Skips nodes below the minimum word threshold.
        2. Skips nodes that already contain the summary marker.
        3. Generates a summary using the LLM (via ``kernel.organizer`` or a
           simple extractive fallback when no LLM is available).
        4. If not dry-run, appends the summary block via ``kernel.update_many()``.
        5. Deposits pheromone and appends a SwarmAction.

        Args:
            report: Mutable SwarmCycleReport to append actions to.

        Returns:
            The mutated report.
        """
        if not self._is_enabled():
            logger.debug("SummarizerAgent disabled — skipping cycle.")
            return report

        agent_cfg = self.agent_config
        dry_run = self._effective_dry_run()

        # Heuristic: long, frequently-accessed, unsummarised nodes are most desirable
        def heuristic_fn(node) -> float:
            words = len(node.content.split())
            length_score = min(words / 500, 1.0) * 0.5
            access_score = min(node.access_count / 10, 1.0) * 0.3
            # Penalise nodes that already have a summary
            already_summarised = _SUMMARY_MARKER in node.content
            novelty_score = 0.0 if already_summarised else 0.2
            return length_score + access_score + novelty_score

        candidates = self._candidate_nodes(
            top_k=agent_cfg.max_nodes_per_cycle,
            heuristic_fn=heuristic_fn,
        )

        if not candidates:
            logger.debug("SummarizerAgent: no candidate nodes found.")
            return report

        report.nodes_processed += len(candidates)

        for node in candidates:
            action: SwarmAction | None = None
            try:
                word_count = len(node.content.split())

                # Skip short notes
                if word_count < _MIN_WORDS_FOR_SUMMARY:
                    self._deposit_pheromone(
                        node_id=node.id,
                        signal_type="skipped",
                        strength=0.2,
                        payload={"reason": "content_too_short", "words": word_count},
                    )
                    action = self._make_skip_action(node.id, reason="content_too_short")
                    report.actions.append(action)
                    continue

                # Skip already-summarised nodes
                if _SUMMARY_MARKER in node.content:
                    self._deposit_pheromone(
                        node_id=node.id,
                        signal_type="skipped",
                        strength=0.3,
                        payload={"reason": "already_summarised"},
                    )
                    action = self._make_skip_action(
                        node.id, reason="already_summarised"
                    )
                    report.actions.append(action)
                    continue

                # Generate summary
                summary_text = await self._generate_summary(node.content, node.title)

                if not summary_text:
                    self._deposit_pheromone(
                        node_id=node.id,
                        signal_type="skipped",
                        strength=0.2,
                        payload={"reason": "summary_generation_failed"},
                    )
                    action = self._make_skip_action(
                        node.id, reason="summary_generation_failed"
                    )
                    report.actions.append(action)
                    continue

                # Build summary block with marker
                summary_block = (
                    f"\n\n{_SUMMARY_MARKER}\n" f"## Summary\n\n" f"{summary_text}\n"
                )

                confidence = min(word_count / 500, 1.0) * 0.8

                applied = False
                if not dry_run:
                    updated_ids, errors = self.kernel.update_many(
                        [(node.id, {"content": summary_block})]
                    )
                    applied = bool(updated_ids)
                    if errors:
                        err_msg = str(errors[0][1])
                        logger.warning(
                            "SummarizerAgent: update_many error for node %s: %s",
                            node.id,
                            err_msg,
                        )

                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="summarize",
                    payload={
                        "summary": summary_text,
                        "word_count": word_count,
                        "summary_words": len(summary_text.split()),
                    },
                    confidence=confidence,
                    applied=applied,
                    dry_run=dry_run,
                )

                self._deposit_pheromone(
                    node_id=node.id,
                    signal_type="summarised",
                    strength=confidence,
                    payload={"summary_added": True, "word_count": word_count},
                )

                logger.debug(
                    "SummarizerAgent: node=%s words=%d applied=%s dry_run=%s",
                    node.id,
                    word_count,
                    applied,
                    dry_run,
                )

            except Exception as exc:
                msg = str(exc)
                logger.warning(
                    "SummarizerAgent: error processing node %s: %s", node.id, msg
                )
                report.add_error(self.agent_type, node.id, msg)
                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="summarize",
                    payload={},
                    confidence=0.0,
                    applied=False,
                    dry_run=dry_run,
                    error=msg,
                )

            if action is not None:
                report.actions.append(action)

        return report

    async def _generate_summary(self, content: str, title: str) -> str:
        """Generate a short summary for the given note content.

        Attempts to use the kernel's LLM client (``kernel.organizer``) if
        available.  Falls back to a simple extractive approach (first N
        sentences) when no LLM is configured.

        Args:
            content: Full note content to summarise.
            title:   Note title (used as context hint for LLM prompt).

        Returns:
            Summary string, or empty string if generation fails.
        """
        # --- LLM path ---
        llm_client = getattr(self.kernel, "llm_client", None)
        if llm_client is not None:
            try:
                prompt = (
                    f"Write a concise 2-3 sentence TL;DR summary for the following note.\n"
                    f"Note title: {title}\n\n"
                    f"Content:\n{content[:2000]}\n\n"
                    f"Summary:"
                )
                # Support both sync and async LLM clients
                if hasattr(llm_client, "complete_async"):
                    response = await llm_client.complete_async(prompt)
                elif hasattr(llm_client, "complete"):
                    import asyncio

                    response = await asyncio.to_thread(llm_client.complete, prompt)
                elif callable(llm_client):
                    import asyncio

                    response = await asyncio.to_thread(llm_client, prompt)
                else:
                    response = None

                if response and isinstance(response, str) and response.strip():
                    return response.strip()
            except Exception as exc:
                logger.debug(
                    "SummarizerAgent: LLM summary generation failed for '%s': %s",
                    title,
                    exc,
                )

        # --- Extractive fallback: first 3 non-empty sentences ---
        import re

        sentences = re.split(r"(?<=[.!?])\s+", content.strip())
        non_empty = [
            s.strip() for s in sentences if s.strip() and not s.startswith("#")
        ]
        if not non_empty:
            return ""
        summary_sentences = non_empty[:3]
        return " ".join(summary_sentences)
