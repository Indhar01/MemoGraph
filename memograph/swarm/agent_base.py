"""
SwarmAgent base class, SwarmAction, and SwarmCycleReport for MemoGraph swarm intelligence.

All concrete agents (TaggerAgent, LinkerAgent, etc.) inherit from SwarmAgent and
implement the ``run_cycle()`` coroutine which is called by the SwarmOrchestrator.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memograph.core.kernel import MemoryKernel
    from memograph.core.node import MemoryNode
    from memograph.swarm.config import AgentConfig, SwarmConfig
    from memograph.swarm.pheromone import PheromoneMap

logger = logging.getLogger("memograph.swarm.agent")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SwarmAction:
    """
    A single proposed or applied action from a swarm agent.

    Each action represents one change (or non-change) that an agent decided
    to make on a memory node.  When ``SwarmConfig.dry_run`` or
    ``AgentConfig.dry_run`` is True the action is recorded but not applied.

    Attributes:
        node_id:    Target memory node ID.
        agent_type: Agent that generated the action ("tagger", "linker", …).
        action_type: What the action does:
            "add_tags"         — add new tags to a node
            "add_links"        — add wikilinks to a node
            "boost_salience"   — increase salience score
            "decay_salience"   — decrease salience score (no recent access)
            "flag_gap"         — flag a knowledge gap
            "summarize"        — append a TL;DR summary to a node
            "skip"             — node was evaluated but no change needed
        payload:    Action-specific data (e.g. {"tags": ["python", "async"]}).
        confidence: Agent confidence in this action, 0.0-1.0.
        applied:    True after the action has been written to the vault.
        dry_run:    True if this action was NOT written (dry-run mode).
        timestamp:  ISO 8601 creation timestamp.
        error:      Non-None if the action failed during apply.

    Example:
        >>> action = SwarmAction(
        ...     node_id="my-note",
        ...     agent_type="tagger",
        ...     action_type="add_tags",
        ...     payload={"tags": ["python"]},
        ...     confidence=0.85,
        ... )
    """

    node_id: str
    agent_type: str
    action_type: str  # "add_tags" | "add_links" | "boost_salience" | "decay_salience" | "flag_gap" | "summarize" | "skip"
    payload: dict = field(default_factory=dict)
    confidence: float = 0.0
    applied: bool = False
    dry_run: bool = False
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise action to a plain dictionary."""
        return {
            "node_id": self.node_id,
            "agent_type": self.agent_type,
            "action_type": self.action_type,
            "payload": self.payload,
            "confidence": self.confidence,
            "applied": self.applied,
            "dry_run": self.dry_run,
            "timestamp": self.timestamp,
            "error": self.error,
        }


@dataclass
class SwarmCycleReport:
    """
    Summary report produced after one full swarm cycle.

    Collected by the SwarmOrchestrator and optionally persisted to disk.

    Attributes:
        cycle_id:          Monotonically increasing integer identifier.
        started_at:        ISO 8601 start timestamp.
        finished_at:       ISO 8601 finish timestamp (set when cycle ends).
        agents_run:        List of agent type strings that executed.
        actions:           All SwarmAction objects produced this cycle.
        nodes_processed:   Total nodes visited across all agents.
        nodes_modified:    Nodes that had at least one action applied.
        errors:            List of (agent_type, node_id, error_message) tuples.
        pheromone_summary: Snapshot from PheromoneMap.summary().
        dry_run:           Whether this cycle ran in dry-run mode.

    Example:
        >>> report = SwarmCycleReport(cycle_id=1)
        >>> report.actions.append(my_action)
        >>> print(f"Actions: {len(report.actions)}")
        Actions: 1
    """

    cycle_id: int
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: str | None = None
    agents_run: list[str] = field(default_factory=list)
    actions: list[SwarmAction] = field(default_factory=list)
    nodes_processed: int = 0
    nodes_modified: int = 0
    errors: list[tuple[str, str, str]] = field(default_factory=list)
    pheromone_summary: dict = field(default_factory=dict)
    dry_run: bool = False

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def finish(self) -> None:
        """Stamp the finished_at timestamp."""
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def add_error(self, agent_type: str, node_id: str, message: str) -> None:
        """Append an error tuple to the errors list."""
        self.errors.append((agent_type, node_id, message))

    @property
    def applied_actions(self) -> list[SwarmAction]:
        """Return only actions that were successfully applied."""
        return [a for a in self.actions if a.applied]

    @property
    def skipped_actions(self) -> list[SwarmAction]:
        """Return only skip actions."""
        return [a for a in self.actions if a.action_type == "skip"]

    @property
    def duration_seconds(self) -> float | None:
        """Return cycle duration in seconds, or None if not finished."""
        if self.finished_at is None:
            return None
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.finished_at)
        return (end - start).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """Serialise report to a plain dictionary."""
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "agents_run": self.agents_run,
            "nodes_processed": self.nodes_processed,
            "nodes_modified": self.nodes_modified,
            "actions_total": len(self.actions),
            "actions_applied": len(self.applied_actions),
            "actions_skipped": len(self.skipped_actions),
            "errors": [
                {"agent": a, "node": n, "message": m} for a, n, m in self.errors
            ],
            "pheromone_summary": self.pheromone_summary,
            "dry_run": self.dry_run,
        }


# ---------------------------------------------------------------------------
# Abstract base agent
# ---------------------------------------------------------------------------


class SwarmAgent(ABC):
    """Abstract base class for all MemoGraph swarm agents.

    Concrete agents override ``run_cycle`` to implement their specific
    knowledge-curation logic. The orchestrator calls ``run_cycle`` once per
    scheduling interval and collects the returned SwarmCycleReport.
    """

    agent_type: str = "base"

    def __init__(
        self,
        kernel: "MemoryKernel",
        pheromone: "PheromoneMap",
        config: "SwarmConfig",
        agent_config: "AgentConfig",
    ) -> None:
        self.kernel = kernel
        self.pheromone = pheromone
        self.config = config
        self.agent_config = agent_config
        self._log = logging.getLogger(f"memograph.swarm.{self.agent_type}")

    @abstractmethod
    async def run_cycle(self, report: SwarmCycleReport) -> SwarmCycleReport:
        """Execute one curation cycle and append actions to ``report``.

        Implementations should:
        1. Call ``_candidate_nodes()`` to get ACO-ranked nodes.
        2. Evaluate each node and build SwarmAction objects.
        3. If not dry-run, apply changes via ``self.kernel``.
        4. Call ``_deposit_pheromone()`` after processing each node.
        5. Append all actions to ``report.actions`` and update counters.
        6. Return the mutated ``report``.
        """

    def _is_enabled(self) -> bool:
        """Return True when this agent should run."""
        return self.agent_config.enabled

    def _effective_dry_run(self) -> bool:
        """Return True if either global or per-agent dry_run is active."""
        return self.config.dry_run or self.agent_config.dry_run

    def _candidate_nodes(
        self,
        top_k: int | None = None,
        heuristic_fn: Any | None = None,
    ) -> list["MemoryNode"]:
        """Return nodes ranked by ACO attractiveness for this agent.

        Dirty nodes (recently created/modified since last cycle) are
        prioritized. Nodes that were visited by this agent within
        ``agent_config.cooldown_seconds`` are excluded.

        Args:
            top_k:        Override ``agent_config.max_nodes_per_cycle``.
            heuristic_fn: Optional callable ``(node) -> float`` in [0.0, 1.0].

        Returns:
            List of MemoryNode objects sorted by ACO attractiveness,
            with dirty nodes appearing first.
        """
        limit = top_k if top_k is not None else self.agent_config.max_nodes_per_cycle
        all_nodes = self.kernel.graph.all_nodes()
        if not all_nodes:
            return []

        # Filter out nodes on cooldown (recently visited by this agent)
        cooldown = self.agent_config.cooldown_seconds
        if cooldown > 0:
            eligible_nodes = [
                n
                for n in all_nodes
                if not self.pheromone.was_visited_recently(
                    n.id, self.agent_type, within_seconds=cooldown
                )
            ]
        else:
            eligible_nodes = all_nodes

        if not eligible_nodes:
            self._log.debug("All nodes on cooldown for agent %s", self.agent_type)
            return []

        # Separate dirty (recently modified) nodes from the rest
        dirty_ids: set[str] = set()
        swarm = getattr(self.kernel, "swarm", None)
        if swarm is not None:
            dirty_ids = swarm.dirty_node_ids

        dirty_nodes = [n for n in eligible_nodes if n.id in dirty_ids]
        other_nodes = [n for n in eligible_nodes if n.id not in dirty_ids]

        # Dirty nodes get automatic priority (no ACO ranking needed)
        result: list["MemoryNode"] = dirty_nodes[:limit]
        remaining_slots = limit - len(result)

        if remaining_slots > 0 and other_nodes:
            if heuristic_fn is not None:
                heuristics = {n.id: float(heuristic_fn(n)) for n in other_nodes}
            else:
                heuristics = {n.id: 0.5 for n in other_nodes}
            ranked = self.pheromone.rank_nodes(
                node_ids=[n.id for n in other_nodes],
                heuristics=heuristics,
                alpha=self.config.alpha,
                beta=self.config.beta,
                top_k=remaining_slots,
            )
            id_to_node = {n.id: n for n in other_nodes}
            result.extend(id_to_node[nid] for nid, _ in ranked if nid in id_to_node)

        return result

    def _deposit_pheromone(
        self,
        node_id: str,
        signal_type: str,
        strength: float = 0.8,
        payload: dict | None = None,
    ) -> None:
        """Deposit a pheromone on a node after processing it.

        Args:
            node_id:     The processed node's ID.
            signal_type: Outcome signal ("tagged", "linked", "skipped", etc.).
            strength:    Pheromone strength to deposit, 0.0-1.0.
            payload:     Optional metadata dict.
        """
        self.pheromone.deposit(
            node_id=node_id,
            agent_type=self.agent_type,
            signal_type=signal_type,
            strength=strength,
            payload=payload or {},
        )

    def _make_skip_action(self, node_id: str, reason: str = "") -> SwarmAction:
        """Build a skip SwarmAction for a node that needs no changes."""
        return SwarmAction(
            node_id=node_id,
            agent_type=self.agent_type,
            action_type="skip",
            payload={"reason": reason},
            confidence=1.0,
            applied=False,
            dry_run=self._effective_dry_run(),
        )

    def __repr__(self) -> str:
        enabled = self.agent_config.enabled
        dry = self._effective_dry_run()
        return f"<{self.__class__.__name__} agent_type={self.agent_type!r} enabled={enabled} dry_run={dry}>"
