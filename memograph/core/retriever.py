# core/retriever.py
import math
import re

from .enums import MemoryType
from .graph import VaultGraph
from .node import MemoryNode


_BM25_K1 = 1.5
_BM25_B = 0.75
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have he in is it its of on or that the "
    "this to was were will with you your i my we our they their he she him her them "
    "what which who whom whose where when why how do does did done can could should "
    "would not no but if then so than into about over more most some any all each".split()
)


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [
        t
        for t in (m.group(0).lower() for m in _TOKEN_RE.finditer(text))
        if t and t not in _STOPWORDS
    ]


class HybridRetriever:
    def __init__(self, graph: VaultGraph, embedding_adapter=None):
        self.graph = graph
        self.embeddings = embedding_adapter  # Optional

    def retrieve(
        self,
        query: str,
        seed_ids: list[str] | None = None,
        tags: list[str] | None = None,
        memory_type: MemoryType | None = None,
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
        filters_active = (
            (tags is not None) or (memory_type is not None) or (min_salience > 0.0)
        )

        if filters_active or not candidates:
            filtered = self.graph.filter(
                tags=tags, memory_type=memory_type, min_salience=min_salience
            )
            for n in filtered:
                candidates[n.id] = n

        # 3. Re-rank candidates by query relevance.
        results_list: list[MemoryNode]
        node_list = list(candidates.values())
        if self.embeddings and query:
            results_list = self._rerank(query, node_list)
        elif query:
            results_list = self._bm25_rank(query, node_list)
        else:
            results_list = sorted(
                node_list,
                key=lambda n: (n.salience, n.access_count),
                reverse=True,
            )

        return results_list[:top_k]

    def _bm25_rank(self, query: str, nodes: list[MemoryNode]) -> list[MemoryNode]:
        """Rank candidates by Okapi BM25 over title + content.

        Used when no embedding adapter is configured and a query string is provided.
        Falls back to salience ordering if every score is zero (no term overlap).
        """
        if not nodes:
            return []
        docs = [_tokenize(f"{n.title}\n{n.content or ''}") for n in nodes]
        q_tokens = _tokenize(query)
        if not q_tokens:
            return sorted(
                nodes, key=lambda n: (n.salience, n.access_count), reverse=True
            )

        N = len(docs)
        avgdl = sum(len(d) for d in docs) / N if N else 0.0

        df: dict[str, int] = {}
        for d in docs:
            for t in set(d):
                df[t] = df.get(t, 0) + 1

        idf = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

        scores: list[float] = []
        for d in docs:
            if not d:
                scores.append(0.0)
                continue
            dl = len(d)
            tf: dict[str, int] = {}
            for t in d:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for q in q_tokens:
                if q not in idf:
                    continue
                f = tf.get(q, 0)
                if f == 0:
                    continue
                denom = (
                    f + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avgdl)
                    if avgdl
                    else f + _BM25_K1
                )
                score += idf[q] * (f * (_BM25_K1 + 1)) / denom
            scores.append(score)

        if all(s == 0.0 for s in scores):
            return sorted(
                nodes, key=lambda n: (n.salience, n.access_count), reverse=True
            )

        order = sorted(
            range(N), key=lambda i: (scores[i], nodes[i].salience), reverse=True
        )
        return [nodes[i] for i in order]

    def _rerank(self, query: str, nodes: list[MemoryNode]) -> list[MemoryNode]:
        q_emb = self.embeddings.embed(query)
        scored = []
        for node in nodes:
            if node.embedding is None:
                node.embedding = self.embeddings.embed(node.content)
            sim = self._cosine_similarity(q_emb, node.embedding)
            scored.append((sim, node))
        return [n for _, n in sorted(scored, key=lambda x: x[0], reverse=True)]

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

        similarity: float = dot_product / (mag_left * mag_right)
        return similarity
