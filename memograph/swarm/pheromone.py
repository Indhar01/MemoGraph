"""
PheromoneMap — Stigmergy layer for MemoGraph swarm intelligence.

Implements ACO-inspired pheromone trails on memory nodes.
Agents deposit pheromones when they process a node; pheromones evaporate
over time, naturally directing agents toward unattended nodes.
"""

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("memograph.swarm.pheromone")


@dataclass
class PheromoneDeposit:
    """A single pheromone deposit left by an agent on a node."""

    node_id: str
    agent_type: str  # "tagger" | "linker" | "gap" | "salience" | "summarizer"
    signal_type: (
        str  # "tagged" | "linked" | "gap_found" | "salience_boosted" | "skipped"
    )
    strength: float  # 0.0-1.0, decays over time
    timestamp: str  # ISO 8601
    payload: dict = field(default_factory=dict)  # agent-specific metadata


class PheromoneMap:
    """
    Persistent pheromone map for stigmergic agent coordination.

    Maintains per-node pheromone deposits from all agents.
    Evaporation reduces deposit strength over time, ensuring
    neglected nodes eventually attract agent attention again.

    Example:
        >>> pmap = PheromoneMap()
        >>> pmap.deposit("node-abc", "tagger", "tagged", strength=0.8)
        >>> score = pmap.get_total_strength("node-abc")
        >>> print(f"Pheromone strength: {score:.2f}")
        Pheromone strength: 0.80
    """

    def __init__(
        self,
        persist_path: Path | None = None,
        max_deposits_per_node: int = 10,
    ) -> None:
        """
        Initialise an empty pheromone map.

        Args:
            persist_path: Optional file path for JSON persistence.
                          If the file already exists it is loaded on init.
            max_deposits_per_node: Maximum deposits retained per node. When
                exceeded, the weakest (lowest strength) deposits are pruned.
        """
        self._deposits: dict[str, list[PheromoneDeposit]] = defaultdict(list)
        self._persist_path = persist_path
        self._evaporation_count: int = 0
        self._max_deposits_per_node = max_deposits_per_node

        if persist_path and Path(persist_path).exists():
            self.load(Path(persist_path))

    # ------------------------------------------------------------------
    # Core deposit / query API
    # ------------------------------------------------------------------

    def deposit(
        self,
        node_id: str,
        agent_type: str,
        signal_type: str,
        strength: float = 1.0,
        payload: dict | None = None,
    ) -> PheromoneDeposit:
        """Leave a pheromone deposit on a node.

        Args:
            node_id:     ID of the memory node being marked.
            agent_type:  Which agent is depositing ("tagger", "linker", etc.).
            signal_type: What the agent did ("tagged", "linked", "skipped", etc.).
            strength:    Initial deposit strength, 0.0-1.0.
            payload:     Optional dict of extra agent metadata to store.

        Returns:
            The newly created PheromoneDeposit.
        """
        strength = max(0.0, min(1.0, strength))
        dep = PheromoneDeposit(
            node_id=node_id,
            agent_type=agent_type,
            signal_type=signal_type,
            strength=strength,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload or {},
        )
        self._deposits[node_id].append(dep)

        # Prune weakest deposits if node exceeds the per-node limit
        node_deps = self._deposits[node_id]
        if len(node_deps) > self._max_deposits_per_node:
            node_deps.sort(key=lambda d: d.strength, reverse=True)
            self._deposits[node_id] = node_deps[: self._max_deposits_per_node]

        logger.debug(
            "Deposited pheromone: node=%s agent=%s signal=%s strength=%.2f",
            node_id,
            agent_type,
            signal_type,
            strength,
        )
        return dep

    def get_deposits(self, node_id: str) -> list[PheromoneDeposit]:
        """Return all active pheromone deposits for a node (copy)."""
        return list(self._deposits.get(node_id, []))

    def get_total_strength(self, node_id: str) -> float:
        """Aggregate pheromone strength for a node across all agents (capped at 1.0)."""
        deposits = self._deposits.get(node_id, [])
        if not deposits:
            return 0.0
        return min(sum(d.strength for d in deposits), 1.0)

    def get_agent_strength(self, node_id: str, agent_type: str) -> float:
        """Return total pheromone strength deposited by a specific agent type."""
        deposits = self._deposits.get(node_id, [])
        return min(sum(d.strength for d in deposits if d.agent_type == agent_type), 1.0)

    def last_visited_by(self, node_id: str, agent_type: str) -> datetime | None:
        """Return the timestamp of the most recent deposit by a given agent type."""
        deposits = [
            d for d in self._deposits.get(node_id, []) if d.agent_type == agent_type
        ]
        if not deposits:
            return None
        latest = max(deposits, key=lambda d: d.timestamp)
        return datetime.fromisoformat(latest.timestamp)

    def was_visited_recently(
        self,
        node_id: str,
        agent_type: str,
        within_seconds: float = 3600.0,
    ) -> bool:
        """Return True if an agent visited this node within ``within_seconds``."""
        last_ts = self.last_visited_by(node_id, agent_type)
        if last_ts is None:
            return False
        now = datetime.now(timezone.utc)
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        return (now - last_ts).total_seconds() < within_seconds

    # ------------------------------------------------------------------
    # ACO selection helper
    # ------------------------------------------------------------------

    def aco_score(
        self,
        node_id: str,
        heuristic: float,
        alpha: float = 1.0,
        beta: float = 2.0,
    ) -> float:
        """Compute an ACO attractiveness score for a node.

        Score = (1 - pheromone)^alpha * heuristic^beta

        High pheromone means the node was recently processed and is less
        attractive. High heuristic means the node needs more attention.

        Args:
            node_id:   Memory node ID.
            heuristic: Desirability signal in [0.0, 1.0] from the agent.
            alpha:     Pheromone avoidance exponent (SwarmConfig.alpha).
            beta:      Heuristic weight exponent (SwarmConfig.beta).

        Returns:
            Float score >= 0.0. Higher = more attractive to visit.
        """
        pheromone = self.get_total_strength(node_id)
        avoidance = (1.0 - pheromone) ** alpha
        desirability = max(heuristic, 0.0) ** beta
        return avoidance * desirability

    def rank_nodes(
        self,
        node_ids: list[str],
        heuristics: dict[str, float],
        alpha: float = 1.0,
        beta: float = 2.0,
        top_k: int | None = None,
    ) -> list[tuple[str, float]]:
        """Rank a list of nodes by ACO attractiveness score.

        Args:
            node_ids:   Candidate node IDs to rank.
            heuristics: Mapping node_id -> heuristic desirability [0.0, 1.0].
            alpha:      Pheromone avoidance exponent.
            beta:       Heuristic weight exponent.
            top_k:      If given, return only the top-k entries.

        Returns:
            List of (node_id, score) tuples sorted descending by score.
        """
        scored = [
            (nid, self.aco_score(nid, heuristics.get(nid, 0.5), alpha, beta))
            for nid in node_ids
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        if top_k is not None:
            return scored[:top_k]
        return scored

    # ------------------------------------------------------------------
    # Evaporation
    # ------------------------------------------------------------------

    def evaporate(self, rate: float = 0.05) -> int:
        """Apply pheromone evaporation across all deposits.

        Each deposit's strength is multiplied by (1 - rate).
        Deposits that fall below 0.001 are pruned.

        Args:
            rate: Fraction to evaporate per call, 0.0-1.0.

        Returns:
            Number of deposits pruned.
        """
        rate = max(0.0, min(1.0, rate))
        prune_threshold = 0.001
        pruned = 0
        for node_id in list(self._deposits.keys()):
            surviving: list[PheromoneDeposit] = []
            for dep in self._deposits[node_id]:
                dep.strength *= 1.0 - rate
                if dep.strength >= prune_threshold:
                    surviving.append(dep)
                else:
                    pruned += 1
            if surviving:
                self._deposits[node_id] = surviving
            else:
                del self._deposits[node_id]
        self._evaporation_count += 1
        logger.debug(
            "Evaporation #%d (rate=%.3f): pruned %d deposits",
            self._evaporation_count,
            rate,
            pruned,
        )
        return pruned

    # ------------------------------------------------------------------
    # Bulk helpers
    # ------------------------------------------------------------------

    def all_node_ids(self) -> list[str]:
        """Return all node IDs that have at least one active deposit."""
        return list(self._deposits.keys())

    def node_count(self) -> int:
        """Return the number of nodes with active pheromone deposits."""
        return len(self._deposits)

    def total_deposit_count(self) -> int:
        """Return the total number of individual deposits in the map."""
        return sum(len(v) for v in self._deposits.values())

    def clear(self) -> None:
        """Remove all pheromone deposits."""
        self._deposits.clear()
        logger.info("PheromoneMap cleared.")

    def summary(self) -> dict:
        """Return a summary dict of the current pheromone map state."""
        top_nodes = sorted(
            [(nid, self.get_total_strength(nid)) for nid in self._deposits],
            key=lambda x: x[1],
            reverse=True,
        )[:10]
        return {
            "node_count": self.node_count(),
            "deposit_count": self.total_deposit_count(),
            "evaporation_cycles": self._evaporation_count,
            "top_nodes": top_nodes,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path | None = None) -> None:
        """Persist the pheromone map to a JSON file.

        Args:
            path: Destination file. Falls back to ``self._persist_path``.
        """
        target = path or self._persist_path
        if target is None:
            logger.warning("PheromoneMap.save(): no persist_path configured, skipping.")
            return
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {
            "evaporation_count": self._evaporation_count,
            "deposits": {
                node_id: [asdict(d) for d in deps]
                for node_id, deps in self._deposits.items()
            },
        }
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        logger.info("PheromoneMap saved to %s (%d nodes)", target, self.node_count())

    def load(self, path: Path) -> None:
        """Load pheromone map state from a JSON file.

        Args:
            path: Source file written by :py:meth:`save`.
        """
        path = Path(path)
        if not path.exists():
            logger.warning("PheromoneMap.load(): file not found: %s", path)
            return
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self._evaporation_count = data.get("evaporation_count", 0)
        self._deposits = defaultdict(list)
        for node_id, dep_list in data.get("deposits", {}).items():
            for dep_dict in dep_list:
                self._deposits[node_id].append(PheromoneDeposit(**dep_dict))
        logger.info("PheromoneMap loaded from %s (%d nodes)", path, self.node_count())
