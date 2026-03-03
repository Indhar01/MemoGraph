# core/retriever.py
from .enums import MemoryType
from .graph import VaultGraph
from .node import MemoryNode


class HybridRetriever:
    def __init__(self, graph: VaultGraph, embedding_adapter=None):
        self.graph = graph
        self.embeddings = embedding_adapter  # Optional

    def retrieve(
        self,
        query: str,
        seed_ids: list[str] = None,
        tags: list[str] = None,
        memory_type: MemoryType = None,
        depth: int = 2,
        top_k: int = 10,
        min_salience: float = 0.0,
    ) -> list[MemoryNode]:

        candidates: dict[str, MemoryNode] = {}

        # 1. Graph traversal from seeds
        for seed_id in seed_ids or []:
            seed = self.graph.get(seed_id)
            if seed:
                candidates[seed.id] = seed
            neighbors = self.graph.neighbors(seed_id, depth=depth)
            for n in neighbors:
                candidates[n.id] = n

        # 2. Metadata filter
        # Only fetch from full graph if filters are applied or we have no seeds
        filters_active = (tags is not None) or (memory_type is not None) or (min_salience > 0.0)

        if filters_active or not candidates:
            filtered = self.graph.filter(
                tags=tags, memory_type=memory_type, min_salience=min_salience
            )
            for n in filtered:
                candidates[n.id] = n

        # 3. Optional: re-rank with vector similarity
        if self.embeddings and query:
            candidates = self._rerank(query, list(candidates.values()))
        else:
            candidates = sorted(
                candidates.values(), key=lambda n: (n.salience, n.access_count), reverse=True
            )

        return candidates[:top_k]

    def _rerank(self, query: str, nodes: list[MemoryNode]) -> list[MemoryNode]:
        q_emb = self.embeddings.embed(query)
        scored = []
        for node in nodes:
            if node.embedding is None:
                node.embedding = self.embeddings.embed(node.content)
            sim = self._cosine_similarity(q_emb, node.embedding)
            scored.append((sim, node))
        return [n for _, n in sorted(scored, reverse=True)]

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        """Calculate cosine similarity between two vectors (normalized dot product)."""
        if not left or not right:
            return 0.0

        size = min(len(left), len(right))
        dot_product = sum(left[i] * right[i] for i in range(size))

        # Calculate magnitudes
        mag_left = sum(x * x for x in left[:size]) ** 0.5
        mag_right = sum(x * x for x in right[:size]) ** 0.5

        if mag_left == 0 or mag_right == 0:
            return 0.0

        return dot_product / (mag_left * mag_right)
