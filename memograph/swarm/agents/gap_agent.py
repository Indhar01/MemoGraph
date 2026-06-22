"""GapAgent — swarm agent that detects knowledge gaps and creates stub notes."""

import logging
from typing import TYPE_CHECKING

from memograph.ai.gap_detector import GapDetector
from memograph.core.enums import MemoryType
from memograph.swarm.agent_base import SwarmAction, SwarmAgent, SwarmCycleReport

if TYPE_CHECKING:
    pass

logger = logging.getLogger("memograph.swarm.gap")


class GapAgent(SwarmAgent):
    """Swarm agent that identifies missing topics and creates placeholder stub notes.

    Uses :class:`~memograph.ai.gap_detector.GapDetector` to find topics that are
    frequently mentioned across the knowledge base but have no dedicated note.
    For each such gap, a stub note is created to serve as a starting point for
    future elaboration.

    Only ``"missing_topic"`` gaps are acted upon — other gap types (weak coverage,
    isolated notes, missing links) are left for other agents or manual curation.

    Example:
        >>> agent = GapAgent(kernel, pheromone, config, config.gap)
        >>> report = await agent.run_cycle(SwarmCycleReport(cycle_id=1))
        >>> print(f"Created {len(report.applied_actions)} stub notes")
    """

    agent_type: str = "gap"

    async def run_cycle(self, report: SwarmCycleReport) -> SwarmCycleReport:
        """Execute one gap-detection cycle.

        Steps:
        1. Runs :class:`~memograph.ai.gap_detector.GapDetector` to detect gaps.
        2. Filters to ``gap_type == "missing_topic"`` gaps only.
        3. Skips topics where a node with a similar title already exists.
        4. If not dry-run, creates a stub note via
           :py:meth:`~memograph.core.kernel.MemoryKernel.remember`.
        5. Deposits pheromone and appends a
           :class:`~memograph.swarm.agent_base.SwarmAction` per gap processed.

        Args:
            report: Mutable SwarmCycleReport to append actions to.

        Returns:
            The mutated report.
        """
        if not self._is_enabled():
            logger.debug("GapAgent disabled — skipping cycle.")
            return report

        agent_cfg = self.agent_config
        dry_run = self._effective_dry_run()

        # Detect gaps using GapDetector
        try:
            detector = GapDetector(
                self.kernel,
                min_severity=0.5,
                max_gaps=agent_cfg.max_nodes_per_cycle,
            )
            all_gaps = await detector.detect_gaps()
        except Exception as exc:
            msg = str(exc)
            logger.warning("GapAgent: gap detection failed: %s", msg)
            report.add_error(self.agent_type, "", msg)
            return report

        # Filter to missing_topic gaps only
        missing_topic_gaps = [g for g in all_gaps if g.gap_type == "missing_topic"]

        if not missing_topic_gaps:
            logger.debug("GapAgent: no missing_topic gaps detected.")
            return report

        report.nodes_processed += len(missing_topic_gaps)

        # Build a set of existing node titles (lowercase) for deduplication
        existing_titles = {node.title.lower() for node in self.kernel.graph.all_nodes()}

        for gap in missing_topic_gaps:
            action: SwarmAction | None = None
            try:
                # Extract the clean topic name from the gap title
                # e.g. "Missing note about 'python'" → "Python"
                raw_title = gap.title
                clean_topic = (
                    raw_title.replace("Missing note about '", "")
                    .replace("'", "")
                    .strip()
                    .title()
                )

                # Skip if a node with a very similar title already exists
                if clean_topic.lower() in existing_titles:
                    logger.debug(
                        "GapAgent: skipping gap '%s' — title already exists.",
                        clean_topic,
                    )
                    action = self._make_skip_action(
                        clean_topic, reason="title_already_exists"
                    )
                    report.actions.append(action)
                    continue

                # Build stub note content
                related_links = "\n".join(f"- [[{n}]]" for n in gap.related_notes[:5])
                stub_content = (
                    f"## {gap.title}\n\n"
                    f"{gap.description}\n\n"
                    f"### Related Notes\n\n"
                    f"{related_links}"
                )

                applied = False
                node_id_created: str | None = None

                if not dry_run:
                    try:
                        file_path = self.kernel.remember(
                            title=clean_topic,
                            content=stub_content,
                            memory_type=MemoryType.SEMANTIC,
                            tags=["stub", "swarm-generated"],
                            salience=0.4,
                        )
                        applied = True
                        node_id_created = file_path
                        # Track this new title to avoid duplicates within the same cycle
                        existing_titles.add(clean_topic.lower())
                        logger.info(
                            "GapAgent: created stub note '%s' at %s",
                            clean_topic,
                            file_path,
                        )
                    except Exception as write_exc:
                        logger.warning(
                            "GapAgent: failed to create stub for '%s': %s",
                            clean_topic,
                            write_exc,
                        )
                        raise

                action = SwarmAction(
                    node_id=clean_topic,
                    agent_type=self.agent_type,
                    action_type="flag_gap",
                    payload={
                        "gap_type": gap.gap_type,
                        "gap_title": gap.title,
                        "clean_topic": clean_topic,
                        "severity": gap.severity,
                        "description": gap.description,
                        "related_notes": gap.related_notes[:5],
                        "stub_created": applied,
                        "file_path": node_id_created,
                    },
                    confidence=gap.severity,
                    applied=applied,
                    dry_run=dry_run,
                )

                self._deposit_pheromone(
                    node_id=clean_topic,
                    signal_type="gap_found",
                    strength=gap.severity,
                    payload={
                        "gap_type": gap.gap_type,
                        "stub_created": applied,
                    },
                )

                logger.debug(
                    "GapAgent: gap=%s severity=%.2f applied=%s dry_run=%s",
                    clean_topic,
                    gap.severity,
                    applied,
                    dry_run,
                )

            except Exception as exc:
                msg = str(exc)
                logger.warning(
                    "GapAgent: error processing gap '%s': %s",
                    getattr(gap, "title", "unknown"),
                    msg,
                )
                report.add_error(self.agent_type, getattr(gap, "title", ""), msg)
                action = SwarmAction(
                    node_id=getattr(gap, "title", ""),
                    agent_type=self.agent_type,
                    action_type="flag_gap",
                    payload={},
                    confidence=0.0,
                    applied=False,
                    dry_run=dry_run,
                    error=msg,
                )

            if action is not None:
                report.actions.append(action)

        return report
