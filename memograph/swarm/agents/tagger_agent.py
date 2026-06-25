"""TaggerAgent — swarm agent that automatically suggests and applies tags to memory nodes."""

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memograph.swarm.agent_base import SwarmAction, SwarmAgent, SwarmCycleReport

if TYPE_CHECKING:
    pass

logger = logging.getLogger("memograph.swarm.tagger")

# Common stop words to exclude from keyword extraction
_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "don",
        "now",
        "and",
        "but",
        "or",
        "if",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "they",
        "them",
        "their",
        "what",
        "which",
        "who",
        "whom",
    }
)


@dataclass
class _HeuristicTagSuggestion:
    """Lightweight tag suggestion from keyword extraction."""

    tag: str
    confidence: float


class TaggerAgent(SwarmAgent):
    """Swarm agent that detects under-tagged nodes and applies AI-suggested tags.

    Uses :class:`~memograph.ai.auto_tagger.AutoTagger` to generate tag suggestions
    for nodes that have few tags or high access counts (indicating importance).

    The ACO heuristic favours nodes with:
    * Fewer existing tags (needs more categorisation)
    * Higher access counts (frequently accessed = important to tag well)

    Example:
        >>> agent = TaggerAgent(kernel, pheromone, config, config.tagger)
        >>> report = await agent.run_cycle(SwarmCycleReport(cycle_id=1))
        >>> print(f"Tagged {report.nodes_modified} nodes")
    """

    agent_type: str = "tagger"

    async def run_cycle(self, report: SwarmCycleReport) -> SwarmCycleReport:
        """Execute one tagging cycle.

        For each ACO-selected candidate node:
        1. Calls AutoTagger to suggest tags for the node.
        2. Filters suggestions below the confidence threshold.
        3. If not dry-run, applies new tags via ``kernel.update_many()``.
        4. Deposits pheromone based on outcome.
        5. Appends a :class:`~memograph.swarm.agent_base.SwarmAction` to the report.

        Args:
            report: Mutable SwarmCycleReport to append actions to.

        Returns:
            The mutated report.
        """
        if not self._is_enabled():
            logger.debug("TaggerAgent disabled — skipping cycle.")
            return report

        config = self.config
        agent_cfg = self.agent_config
        dry_run = self._effective_dry_run()

        # Heuristic: nodes with few tags and high access count are most desirable
        def heuristic_fn(node) -> float:
            tag_score = (max(0, 3 - len(node.tags)) / 3) * 0.6
            access_score = min(node.access_count / 10, 1.0) * 0.4
            return tag_score + access_score

        candidates = self._candidate_nodes(
            top_k=agent_cfg.max_nodes_per_cycle,
            heuristic_fn=heuristic_fn,
        )

        if not candidates:
            logger.debug("TaggerAgent: no candidate nodes found.")
            return report

        report.nodes_processed += len(candidates)

        for node in candidates:
            action: SwarmAction | None = None
            try:
                suggestions = await self._get_tag_suggestions(node, agent_cfg, config)

                # Filter by confidence threshold
                approved = [
                    s
                    for s in suggestions
                    if s.confidence >= agent_cfg.confidence_threshold
                ]

                if not approved:
                    # No new tags — deposit skipped pheromone
                    self._deposit_pheromone(
                        node_id=node.id,
                        signal_type="skipped",
                        strength=0.3,
                        payload={"reason": "no_approved_tags"},
                    )
                    action = self._make_skip_action(node.id, reason="no_approved_tags")
                    report.actions.append(action)
                    continue

                new_tags = [s.tag for s in approved]
                avg_confidence = sum(s.confidence for s in approved) / len(approved)
                confidence_scores = {s.tag: s.confidence for s in approved}

                applied = False
                if not dry_run:
                    updated_ids, errors = self.kernel.update_many(
                        [(node.id, {"tags": node.tags + new_tags})]
                    )
                    applied = bool(updated_ids)
                    if errors:
                        err_msg = str(errors[0][1])
                        logger.warning(
                            "TaggerAgent: update_many error for node %s: %s",
                            node.id,
                            err_msg,
                        )

                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="add_tags",
                    payload={
                        "tags_added": new_tags,
                        "confidence_scores": confidence_scores,
                    },
                    confidence=avg_confidence,
                    applied=applied,
                    dry_run=dry_run,
                )

                # Deposit pheromone: high-confidence tagging leaves a strong trail
                self._deposit_pheromone(
                    node_id=node.id,
                    signal_type="tagged",
                    strength=avg_confidence,
                    payload={"tags_added": new_tags},
                )

                logger.debug(
                    "TaggerAgent: node=%s new_tags=%s applied=%s dry_run=%s",
                    node.id,
                    new_tags,
                    applied,
                    dry_run,
                )

            except Exception as exc:
                msg = str(exc)
                logger.warning(
                    "TaggerAgent: error processing node %s: %s", node.id, msg
                )
                report.add_error(self.agent_type, node.id, msg)
                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="add_tags",
                    payload={},
                    confidence=0.0,
                    applied=False,
                    dry_run=dry_run,
                    error=msg,
                )

            if action is not None:
                report.actions.append(action)

        return report

    async def _get_tag_suggestions(self, node, agent_cfg, config):
        """Get tag suggestions via AI, falling back to keyword extraction.

        Tries AutoTagger first. If it fails (no LLM, import error, API error),
        falls back to heuristic keyword frequency extraction.
        """
        try:
            from memograph.ai.auto_tagger import AutoTagger

            tagger = AutoTagger(
                self.kernel,
                min_confidence=agent_cfg.confidence_threshold,
                max_suggestions=config.max_tags_per_cycle,
            )
            return await tagger.suggest_tags(
                content=node.content,
                title=node.title,
                existing_tags=node.tags,
            )
        except Exception as ai_exc:
            logger.debug(
                "TaggerAgent: AI tagger unavailable (%s), using heuristic",
                ai_exc,
            )
            return self._heuristic_tag_suggestions(
                node.content, node.title, node.tags, config.max_tags_per_cycle
            )

    def _heuristic_tag_suggestions(
        self,
        content: str,
        title: str,
        existing_tags: list[str],
        max_suggestions: int,
    ) -> list[_HeuristicTagSuggestion]:
        """Extract tags from content using keyword frequency analysis.

        Finds significant words (2+ occurrences, not stop words, not already
        tagged) and returns them as tag suggestions with confidence based on
        relative frequency.
        """
        # Tokenize: lowercase alphanumeric words, 3+ chars
        words = re.findall(r"[a-z][a-z0-9-]{2,}", content.lower())
        title_words = re.findall(r"[a-z][a-z0-9-]{2,}", title.lower())

        # Count frequencies (title words get a 3x boost)
        counts: Counter[str] = Counter()
        for w in words:
            if w not in _STOP_WORDS:
                counts[w] += 1
        for w in title_words:
            if w not in _STOP_WORDS:
                counts[w] += 3

        # Exclude existing tags
        existing_set = {t.lower() for t in existing_tags}
        for tag in existing_set:
            counts.pop(tag, None)

        if not counts:
            return []

        # Normalize confidence by max frequency
        max_count = max(counts.values())
        suggestions = []
        for word, count in counts.most_common(max_suggestions):
            if count < 2:
                break
            confidence = min(count / max_count, 1.0) * 0.75  # cap at 0.75
            suggestions.append(_HeuristicTagSuggestion(tag=word, confidence=confidence))

        return suggestions
