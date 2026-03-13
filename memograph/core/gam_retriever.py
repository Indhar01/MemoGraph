"""
GAM-Enhanced Retriever

Drop-in replacement for HybridRetriever with Graph Attention Memory scoring.
Maintains 100% backward compatibility while adding GAM capabilities.

Usage:
    # Standard retrieval (backward compatible)
    retriever = GAMRetriever(graph, embedding_adapter)
    nodes = retriever.retrieve(query, seed_ids, tags, depth, top_k)

    # With GAM scoring enabled
    retriever = GAMRetriever(graph, embedding_adapter, use_gam=True)
    nodes = retriever.retrieve(query, seed_ids, tags, depth, top_k)
"""

import logging
from typing import TYPE_CHECKING

from .access_tracker import AccessTracker
from .gam_scorer import GAMConfig, GAMScorer
from .retriever import HybridRetriever

if TYPE_CHECKING:
    from .graph import VaultGraph
    from .node import MemoryNode

logger = logging.getLogger("memograph.gam_retriever")


class GAMRetriever(HybridRetriever):
    """
    Enhanced retriever with Graph Attention Memory scoring.

    This retriever extends HybridRetriever by adding:
    1. Graph attention-based relevance scoring
    2. Co-access pattern tracking
    3. Temporal decay for recency bias
    4. Configurable scoring weights

    Maintains 100% backward compatibility - GAM features are opt-in.

    Example:
        >>> # Basic usage (same as HybridRetriever)
        >>> retriever = GAMRetriever(graph, embedding_adapter)
        >>> nodes = retriever.retrieve("python tips", seed_ids, top_k=10)
        >>>
        >>> # With GAM enabled
        >>> config = GAMConfig(
        ...     relationship_weight=0.4,
        ...     recency_weight=0.3,
        ...     salience_weight=0.3
        ... )
        >>> retriever = GAMRetriever(
        ...     graph,
        ...     embedding_adapter,
        ...     use_gam=True,
        ...     gam_config=config
        ... )
        >>> nodes = retriever.retrieve("python tips", seed_ids, top_k=10)
    """

    def __init__(
        self,
        graph: "VaultGraph",
        embedding_adapter=None,
        use_gam: bool = False,
        gam_config: GAMConfig | None = None,
        access_tracker: AccessTracker | None = None,
    ):
        """
        Initialize GAM retriever.

        Args:
            graph: Vault graph
            embedding_adapter: Optional embedding adapter for semantic search
            use_gam: Enable GAM scoring (default: False for backward compatibility)
            gam_config: GAM configuration (uses defaults if None)
            access_tracker: Optional access tracker (creates new one if None and GAM enabled)
        """
        super().__init__(graph, embedding_adapter)

        self.use_gam = use_gam
        self.gam_config = gam_config or GAMConfig()

        # Initialize GAM components if enabled
        if use_gam:
            self.scorer: GAMScorer | None = GAMScorer(self.gam_config)
            self.access_tracker: AccessTracker | None = access_tracker or AccessTracker()
            logger.info("GAM retrieval enabled with config: %s", self.gam_config)
        else:
            self.scorer: GAMScorer | None = None
            self.access_tracker: AccessTracker | None = None
            logger.debug("GAM retrieval disabled (backward compatible mode)")

    def retrieve(
        self,
        query: str,
        seed_ids: list[str] | None = None,
        tags: list[str] | None = None,
        memory_type=None,
        depth: int = 2,
        top_k: int = 8,
        min_salience: float = 0.0,
    ) -> list["MemoryNode"]:
        """
        Retrieve relevant memory nodes.

        If GAM is disabled, behaves identically to HybridRetriever.
        If GAM is enabled, re-ranks results using GAM scores.

        Args:
            query: Search query string
            seed_ids: IDs of seed nodes (starting points)
            tags: Optional tag filter
            memory_type: Optional memory type filter
            depth: Graph traversal depth
            top_k: Maximum results to return
            min_salience: Minimum salience score filter

        Returns:
            List of memory nodes, ranked by relevance
        """
        if not self.use_gam:
            # Backward compatible: use parent implementation
            return super().retrieve(query, seed_ids, tags, memory_type, depth, top_k, min_salience)

        # GAM-enhanced retrieval (seed_ids should not be None for GAM)
        if seed_ids is None:
            seed_ids = []
        return self._gam_retrieve(query, seed_ids, tags, depth, top_k)

    def _gam_retrieve(
        self,
        query: str,
        seed_ids: list[str],
        tags: list[str] | None,
        depth: int,
        top_k: int,
    ) -> list["MemoryNode"]:
        """
        GAM-enhanced retrieval implementation.

        Process:
        1. Get initial candidates using parent HybridRetriever (larger set)
        2. Compute GAM scores for each candidate
        3. Re-rank by GAM score
        4. Track co-access patterns
        5. Return top-k results
        """
        # Get more candidates than needed (2x) for better re-ranking
        initial_top_k = max(top_k * 2, 20)

        # Get initial candidates using standard retrieval
        candidates = super().retrieve(query, seed_ids, tags, None, depth, initial_top_k, 0.0)

        if not candidates:
            logger.debug("No candidates found for query: %s", query)
            return []

        logger.debug(f"Got {len(candidates)} initial candidates, computing GAM scores")

        # Prepare query context for scoring
        query_context = {"query": query, "seed_ids": seed_ids}

        # Score all candidates with GAM
        scored_nodes = []
        for node in candidates:
            gam_score = self.scorer.compute_score(
                node, query_context, self.graph, self.access_tracker
            )
            scored_nodes.append((node, gam_score))

        # Sort by GAM score (descending)
        scored_nodes.sort(key=lambda x: x[1], reverse=True)

        # Take top-k
        top_nodes = [node for node, score in scored_nodes[:top_k]]

        # Track co-access pattern
        if self.access_tracker:
            self.access_tracker.record_access(query, top_nodes)

        logger.info(
            f"GAM retrieval complete: {len(top_nodes)} nodes "
            f"(scores: {scored_nodes[0][1]:.3f} to {scored_nodes[min(len(scored_nodes)-1, top_k-1)][1]:.3f})"
        )

        return top_nodes

    def explain_retrieval(
        self,
        query: str,
        seed_ids: list[str],
        tags: list[str] | None = None,
        depth: int = 2,
        top_k: int = 8,
    ) -> dict:
        """
        Explain the retrieval process with score breakdowns.

        Useful for debugging and understanding why certain memories
        were ranked higher than others.

        Returns:
            Dict with retrieval explanation including:
            - query info
            - candidate count
            - top results with score breakdowns
        """
        if not self.use_gam:
            return {
                "message": "GAM not enabled, no explanation available",
                "use_gam": False,
            }

        # Get candidates
        initial_top_k = max(top_k * 2, 20)
        candidates = super().retrieve(query, seed_ids, tags, None, depth, initial_top_k, 0.0)

        query_context = {"query": query, "seed_ids": seed_ids}

        # Get detailed explanations for top candidates
        explanations = []
        for node in candidates[:top_k]:
            explanation = self.scorer.explain_score(
                node, query_context, self.graph, self.access_tracker
            )
            explanations.append(explanation)

        # Sort by final score
        explanations.sort(key=lambda x: x["final_score"], reverse=True)

        return {
            "query": query,
            "seed_ids": seed_ids,
            "tags": tags,
            "depth": depth,
            "top_k": top_k,
            "candidates_found": len(candidates),
            "gam_config": {
                "relationship_weight": self.gam_config.relationship_weight,
                "co_access_weight": self.gam_config.co_access_weight,
                "recency_weight": self.gam_config.recency_weight,
                "salience_weight": self.gam_config.salience_weight,
            },
            "results": explanations[:top_k],
        }

    def get_access_statistics(self) -> dict:
        """
        Get access tracking statistics.

        Returns:
            Dict with tracker statistics or empty dict if GAM disabled
        """
        if not self.use_gam or not self.access_tracker:
            return {}

        return self.access_tracker.get_statistics()


# Convenience function for quick GAM retrieval
def gam_retrieve(
    graph: "VaultGraph",
    query: str,
    seed_ids: list[str],
    top_k: int = 8,
    gam_config: GAMConfig | None = None,
) -> list["MemoryNode"]:
    """
    Convenience function for one-off GAM retrieval.

    Example:
        >>> nodes = gam_retrieve(graph, "python tips", seed_ids, top_k=10)
    """
    retriever = GAMRetriever(graph, use_gam=True, gam_config=gam_config)
    return retriever.retrieve(query, seed_ids, top_k=top_k)
