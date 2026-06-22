"""SalienceAgent — swarm agent that boosts and decays salience scores on memory nodes."""

import logging
from typing import TYPE_CHECKING

from memograph.swarm.agent_base import SwarmAction, SwarmAgent, SwarmCycleReport

if TYPE_CHECKING:
    pass

logger = logging.getLogger("memograph.swarm.salience")


class SalienceAgent(SwarmAgent):
    """Swarm agent that boosts under-valued nodes and decays over-valued ones.

    Salience is MemoGraph's importance signal (0.0–1.0). This agent performs two passes:

    **Boost pass**: Nodes that are frequently accessed, highly connected, or recently
    created but under-scored get a capped salience increase.

    **Decay pass**: Nodes with high salience but low recent access and low connectivity
    get a capped salience decrease, preventing all nodes from drifting toward 1.0
    over time.

    The agent applies a *capped* boost/decay:
    ``new_salience = clamp(old_salience ± delta, 0.05, 1.0)``

    where ``delta <= SwarmConfig.max_salience_boost``.

    Example:
        >>> agent = SalienceAgent(kernel, pheromone, config, config.salience)
        >>> report = await agent.run_cycle(SwarmCycleReport(cycle_id=1))
        >>> print(f"Adjusted {len(report.applied_actions)} nodes")
    """

    agent_type: str = "salience"

    async def run_cycle(self, report: SwarmCycleReport) -> SwarmCycleReport:
        """Execute one salience-boosting cycle.

        For each ACO-selected candidate node:
        1. Computes a target salience based on access count, link density, and
           number of tags.
        2. Calculates a capped boost (``<= SwarmConfig.max_salience_boost``).
        3. Skips nodes already at or above the target.
        4. If not dry-run, applies via ``kernel.update_many()``.
        5. Deposits pheromone and appends a SwarmAction.

        Args:
            report: Mutable SwarmCycleReport to append actions to.

        Returns:
            The mutated report.
        """
        if not self._is_enabled():
            logger.debug("SalienceAgent disabled — skipping cycle.")
            return report

        config = self.config
        agent_cfg = self.agent_config
        dry_run = self._effective_dry_run()

        all_nodes = self.kernel.graph.all_nodes()
        if not all_nodes:
            logger.debug("SalienceAgent: graph is empty.")
            return report

        # Compute vault-wide access statistics for normalisation
        max_access = max((n.access_count for n in all_nodes), default=1)
        if max_access == 0:
            max_access = 1

        # Heuristic: high-access, well-connected, low-salience nodes need boosting
        def heuristic_fn(node) -> float:
            access_norm = min(node.access_count / max_access, 1.0)
            total_links = len(node.links) + len(node.backlinks)
            link_norm = min(total_links / 10, 1.0)
            # Under-salience factor: nodes below their "deserved" salience score
            deserved = (
                access_norm * 0.5 + link_norm * 0.3 + min(len(node.tags) / 5, 1.0) * 0.2
            )
            gap = max(0.0, deserved - node.salience)
            return gap

        candidates = self._candidate_nodes(
            top_k=agent_cfg.max_nodes_per_cycle,
            heuristic_fn=heuristic_fn,
        )

        if not candidates:
            logger.debug("SalienceAgent: no candidate nodes found.")
            return report

        report.nodes_processed += len(candidates)

        for node in candidates:
            action: SwarmAction | None = None
            try:
                # Compute deserved salience target
                access_norm = min(node.access_count / max_access, 1.0)
                total_links = len(node.links) + len(node.backlinks)
                link_norm = min(total_links / 10, 1.0)
                tag_norm = min(len(node.tags) / 5, 1.0)
                deserved = access_norm * 0.5 + link_norm * 0.3 + tag_norm * 0.2

                # Boost = difference capped at max_salience_boost
                raw_boost = max(0.0, deserved - node.salience)
                boost = min(raw_boost, config.max_salience_boost)

                if boost < 0.01:
                    # Negligible boost — skip this node
                    self._deposit_pheromone(
                        node_id=node.id,
                        signal_type="skipped",
                        strength=0.2,
                        payload={"reason": "salience_already_adequate"},
                    )
                    action = self._make_skip_action(
                        node.id, reason="salience_already_adequate"
                    )
                    report.actions.append(action)
                    continue

                new_salience = min(node.salience + boost, 1.0)
                confidence = boost / config.max_salience_boost  # normalised confidence

                if confidence < agent_cfg.confidence_threshold:
                    self._deposit_pheromone(
                        node_id=node.id,
                        signal_type="skipped",
                        strength=0.2,
                        payload={"reason": "boost_below_threshold"},
                    )
                    action = self._make_skip_action(
                        node.id, reason="boost_below_threshold"
                    )
                    report.actions.append(action)
                    continue

                applied = False
                if not dry_run:
                    updated_ids, errors = self.kernel.update_many(
                        [(node.id, {"salience": new_salience})]
                    )
                    applied = bool(updated_ids)
                    if errors:
                        err_msg = str(errors[0][1])
                        logger.warning(
                            "SalienceAgent: update_many error for node %s: %s",
                            node.id,
                            err_msg,
                        )

                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="boost_salience",
                    payload={
                        "old_salience": node.salience,
                        "new_salience": new_salience,
                        "boost": boost,
                        "access_count": node.access_count,
                        "total_links": total_links,
                        "tag_count": len(node.tags),
                    },
                    confidence=confidence,
                    applied=applied,
                    dry_run=dry_run,
                )

                self._deposit_pheromone(
                    node_id=node.id,
                    signal_type="salience_boosted",
                    strength=confidence,
                    payload={
                        "old_salience": node.salience,
                        "new_salience": new_salience,
                        "boost": boost,
                    },
                )

                logger.debug(
                    "SalienceAgent: node=%s salience %.3f→%.3f boost=%.3f applied=%s",
                    node.id,
                    node.salience,
                    new_salience,
                    boost,
                    applied,
                )

            except Exception as exc:
                msg = str(exc)
                logger.warning(
                    "SalienceAgent: error processing node %s: %s", node.id, msg
                )
                report.add_error(self.agent_type, node.id, msg)
                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="boost_salience",
                    payload={},
                    confidence=0.0,
                    applied=False,
                    dry_run=dry_run,
                    error=msg,
                )

            if action is not None:
                report.actions.append(action)

        # === Decay pass: lower salience for neglected, over-scored nodes ===
        self._decay_pass(all_nodes, max_access, report, dry_run)

        return report

    def _decay_pass(
        self,
        all_nodes: list,
        max_access: int,
        report: SwarmCycleReport,
        dry_run: bool,
    ) -> None:
        """Lower salience for nodes with high salience but low access/connectivity.

        Prevents all nodes from monotonically drifting toward 1.0 over time.
        Only decays nodes where salience exceeds the "deserved" level.
        """
        config = self.config
        agent_cfg = self.agent_config

        # Decay candidates: high salience but low activity
        decay_candidates = [
            n
            for n in all_nodes
            if n.salience > 0.5 and n.access_count < (max_access * 0.2)
        ]

        # Limit to half of max_nodes_per_cycle for decay (boost gets priority)
        decay_limit = max(1, agent_cfg.max_nodes_per_cycle // 2)
        decay_candidates = sorted(
            decay_candidates, key=lambda n: n.salience, reverse=True
        )[:decay_limit]

        for node in decay_candidates:
            action: SwarmAction | None = None
            try:
                access_norm = min(node.access_count / max_access, 1.0)
                total_links = len(node.links) + len(node.backlinks)
                link_norm = min(total_links / 10, 1.0)
                tag_norm = min(len(node.tags) / 5, 1.0)
                deserved = access_norm * 0.5 + link_norm * 0.3 + tag_norm * 0.2

                # Only decay if current salience exceeds deserved level
                overshoot = node.salience - deserved
                if overshoot < 0.05:
                    continue

                # Capped decay (same cap as boost for symmetry)
                decay = min(overshoot * 0.5, config.max_salience_boost)
                new_salience = max(node.salience - decay, 0.05)  # never drop below 0.05

                if abs(new_salience - node.salience) < 0.01:
                    continue

                confidence = decay / config.max_salience_boost

                applied = False
                if not dry_run:
                    updated_ids, errors = self.kernel.update_many(
                        [(node.id, {"salience": new_salience})]
                    )
                    applied = bool(updated_ids)

                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="decay_salience",
                    payload={
                        "old_salience": node.salience,
                        "new_salience": new_salience,
                        "decay": decay,
                        "access_count": node.access_count,
                        "total_links": total_links,
                    },
                    confidence=confidence,
                    applied=applied,
                    dry_run=dry_run,
                )

                self._deposit_pheromone(
                    node_id=node.id,
                    signal_type="salience_decayed",
                    strength=confidence,
                    payload={
                        "old_salience": node.salience,
                        "new_salience": new_salience,
                        "decay": decay,
                    },
                )

                report.nodes_processed += 1

            except Exception as exc:
                msg = str(exc)
                logger.warning(
                    "SalienceAgent decay: error processing node %s: %s", node.id, msg
                )
                report.add_error(self.agent_type, node.id, msg)
                action = SwarmAction(
                    node_id=node.id,
                    agent_type=self.agent_type,
                    action_type="decay_salience",
                    payload={},
                    confidence=0.0,
                    applied=False,
                    dry_run=dry_run,
                    error=msg,
                )

            if action is not None:
                report.actions.append(action)
