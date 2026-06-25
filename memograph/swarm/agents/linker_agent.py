"""LinkerAgent — swarm agent that suggests and applies wikilinks between memory nodes."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memograph.swarm.agent_base import SwarmAction, SwarmAgent, SwarmCycleReport

if TYPE_CHECKING:
    pass

logger = logging.getLogger("memograph.swarm.linker")


@dataclass
class _HeuristicLinkSuggestion:
    """Lightweight link suggestion from title/tag overlap."""

    target_id: str
    target_title: str
    confidence: float


class LinkerAgent(SwarmAgent):
    """Swarm agent that detects under-linked nodes and adds AI-suggested wikilinks.

    Uses :class:`~memograph.ai.link_suggester.LinkSuggester` to generate link
    suggestions for nodes that have few outgoing links or high access counts.

    The ACO heuristic favours nodes with:
    * Fewer existing outgoing links (well-connected notes need less attention)
    * Higher access counts (frequently accessed = important to connect well)

    When applying links, a ``Related: [[target_id]]`` block is appended to the
    node's content via :py:meth:`~memograph.core.kernel.MemoryKernel.update_many`.

    Example:
        >>> agent = LinkerAgent(kernel, pheromone, config, config.linker)
        >>> report = await agent.run_cycle(SwarmCycleReport(cycle_id=1))
        >>> print(f"Linked {report.nodes_modified} nodes")
    """

    agent_type: str = "linker"

    async def run_cycle(self, report: SwarmCycleReport) -> SwarmCycleReport:
        """Execute one linking cycle.

        For each ACO-selected candidate node:
        1. Calls LinkSuggester to find related nodes worth linking.
        2. Filters suggestions below the confidence threshold.
        3. If not dry-run, appends a ``Related:`` wikilink block via
           ``kernel.update_many()``.
        4. Deposits pheromone based on outcome.
        5. Appends a :class:`~memograph.swarm.agent_base.SwarmAction` to the report.

        Args:
            report: Mutable SwarmCycleReport to append actions to.

        Returns:
            The mutated report.
        """
        if not self._is_enabled():
            logger.debug("LinkerAgent disabled — skipping cycle.")
            return report

        agent_cfg = self.agent_config
        dry_run = self._effective_dry_run()

        # Heuristic: nodes with few outgoing links and high access count are most desirable
        def heuristic_fn(node) -> float:
            link_score = (max(0, 5 - len(node.links)) / 5) * 0.7
            access_score = min(node.access_count / 10, 1.0) * 0.3
            return link_score + access_score

        candidates = self._candidate_nodes(
            top_k=agent_cfg.max_nodes_per_cycle,
            heuristic_fn=heuristic_fn,
        )

        if not candidates:
            logger.debug("LinkerAgent: no candidate nodes found.")
            return report

        report.nodes_processed += len(candidates)

        for node in candidates:
            action: SwarmAction | None = None
            try:
                suggestions = await self._get_link_suggestions(node, agent_cfg)

                # Filter by confidence threshold
                approved = [
                    s
                    for s in suggestions
                    if s.confidence >= agent_cfg.confidence_threshold
                ]

                if not approved:
                    self._deposit_pheromone(
                        node_id=node.id,
                        signal_type="skipped",
                        strength=0.3,
                        payload={"reason": "no_approved_links"},
                    )
                    action = self._make_skip_action(node.id, reason="no_approved_links")
                    report.actions.append(action)
                    continue

                target_ids = [s.target_id for s in approved]
                avg_confidence = sum(s.confidence for s in approved) / len(approved)
                targets_info = [
                    {
                        "id": s.target_id,
                        "title": s.target_title,
                        "confidence": s.confidence,
                    }
                    for s in approved
                ]

                applied = False
                if not dry_run:
                    # Build a "Related:" wikilink block appended to content
                    wikilinks = " ".join(f"[[{tid}]]" for tid in target_ids)
                    related_block = f"\n\nRelated: {wikilinks}"

                    updated_ids, errors = self.kernel.update_many(
                        [(node.id, {"content": related_block})]
                    )
                    applied = bool(updated_ids)
                    if errors:
                        err_msg = str(errors[0][1])
                        logger.warning(
                            "LinkerAgent: update_many error for node %s: %s",
                            node.id,
                            err_msg,
                        )

                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="add_links",
                    payload={
                        "links_added": target_ids,
                        "targets": targets_info,
                    },
                    confidence=avg_confidence,
                    applied=applied,
                    dry_run=dry_run,
                )

                self._deposit_pheromone(
                    node_id=node.id,
                    signal_type="linked",
                    strength=avg_confidence,
                    payload={"links_added": target_ids},
                )

                logger.debug(
                    "LinkerAgent: node=%s links_added=%s applied=%s dry_run=%s",
                    node.id,
                    target_ids,
                    applied,
                    dry_run,
                )

            except Exception as exc:
                msg = str(exc)
                logger.warning(
                    "LinkerAgent: error processing node %s: %s", node.id, msg
                )
                report.add_error(self.agent_type, node.id, msg)
                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="add_links",
                    payload={},
                    confidence=0.0,
                    applied=False,
                    dry_run=dry_run,
                    error=msg,
                )

            if action is not None:
                report.actions.append(action)

        return report

    async def _get_link_suggestions(self, node, agent_cfg):
        """Get link suggestions via AI, falling back to tag/title overlap.

        Tries LinkSuggester first. If it fails (no LLM configured),
        uses heuristic overlap scoring between this node and all others.
        """
        try:
            from memograph.ai.link_suggester import LinkSuggester

            suggester = LinkSuggester(
                self.kernel,
                min_confidence=agent_cfg.confidence_threshold,
                max_suggestions=5,
            )
            return await suggester.suggest_links(
                content=node.content,
                title=node.title,
                note_id=node.id,
                existing_links=node.links,
            )
        except Exception as ai_exc:
            logger.debug(
                "LinkerAgent: AI suggester unavailable (%s), using heuristic",
                ai_exc,
            )
            return self._heuristic_link_suggestions(node)

    def _heuristic_link_suggestions(self, node) -> list[_HeuristicLinkSuggestion]:
        """Find related nodes using tag overlap and title-in-content matching.

        Scoring:
        * +0.3 per shared tag (capped at 0.9)
        * +0.4 if the other node's title appears in this node's content
        * +0.2 if this node's title appears in the other node's content

        Only returns suggestions above the confidence threshold.
        """
        all_nodes = self.kernel.graph.all_nodes()
        existing_links = set(node.links)
        node_tags = set(node.tags)
        content_lower = node.content.lower()
        suggestions: list[_HeuristicLinkSuggestion] = []

        for other in all_nodes:
            if other.id == node.id or other.id in existing_links:
                continue

            score = 0.0

            # Tag overlap
            shared_tags = node_tags & set(other.tags)
            score += min(len(shared_tags) * 0.3, 0.9)

            # Title mention: other's title in this node's content
            if other.title.lower() in content_lower:
                score += 0.4

            # Reverse mention: this node's title in other's content
            if node.title.lower() in other.content.lower():
                score += 0.2

            if score >= self.agent_config.confidence_threshold:
                suggestions.append(
                    _HeuristicLinkSuggestion(
                        target_id=other.id,
                        target_title=other.title,
                        confidence=min(score, 1.0),
                    )
                )

        # Sort by confidence descending, take top 5
        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        return suggestions[:5]
