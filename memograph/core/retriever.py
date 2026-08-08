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


# Reciprocal Rank Fusion constant. 60 is the value from the original Cormack
# et al. RRF paper and is robust across corpora; exposed as a module constant
# so it can be tuned without touching call sites.
_RRF_K = 60


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [
        t
        for t in (m.group(0).lower() for m in _TOKEN_RE.finditer(text))
        if t and t not in _STOPWORDS
    ]


def bm25_scores(query: str, nodes: list[MemoryNode]) -> dict[str, float]:
    """Okapi BM25 score for each node's ``title + content`` against ``query``.

    Returns a mapping ``node.id -> score``. Reusable for BOTH seed selection
    (rank the whole vault, take the top-N) and hybrid fusion (one of the two
    rankings fed into RRF). Nodes with no term overlap score 0.0.
    """
    if not nodes:
        return {}
    q_tokens = _tokenize(query)
    if not q_tokens:
        return {n.id: 0.0 for n in nodes}

    docs = [_tokenize(f"{n.title}\n{n.content or ''}") for n in nodes]
    num_docs = len(docs)
    avgdl = sum(len(d) for d in docs) / num_docs if num_docs else 0.0

    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(1 + (num_docs - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    scores: dict[str, float] = {}
    for node, d in zip(nodes, docs):
        if not d:
            scores[node.id] = 0.0
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
        scores[node.id] = score
    return scores


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = _RRF_K
) -> dict[str, float]:
    """Fuse several ranked id-lists into one score map via RRF.

    ``score(id) = sum over rankings of 1 / (k + rank)`` where ``rank`` is the
    0-based position of the id in that ranking. RRF needs no score
    normalization and robustly beats either input ranking alone — the standard
    way to combine lexical (BM25) and semantic (cosine) signals.
    """
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, node_id in enumerate(ranking):
            fused[node_id] = fused.get(node_id, 0.0) + 1.0 / (k + rank)
    return fused


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

        # 2. Metadata filter.
        #
        # Filters (tags / memory_type / min_salience) are RESTRICTIVE, not
        # additive: when active, the final candidate set must satisfy them.
        # We therefore INTERSECT the seed-traversal candidates with the
        # filtered set rather than unioning them (the old behavior leaked
        # seed-neighbors that failed the filter into the results). When there
        # are no seed candidates yet, the filtered set becomes the candidates.
        filters_active = (
            (tags is not None) or (memory_type is not None) or (min_salience > 0.0)
        )

        if filters_active:
            filtered_ids = {
                n.id
                for n in self.graph.filter(
                    tags=tags, memory_type=memory_type, min_salience=min_salience
                )
            }
            if candidates:
                candidates = {
                    nid: n for nid, n in candidates.items() if nid in filtered_ids
                }
            else:
                candidates = {
                    n.id: n
                    for n in self.graph.filter(
                        tags=tags, memory_type=memory_type, min_salience=min_salience
                    )
                }
        elif not candidates:
            # No filters and no seeds: consider the whole graph.
            for n in self.graph.filter(tags=None, memory_type=None, min_salience=0.0):
                candidates[n.id] = n

        # 3. Re-rank candidates by query relevance.
        #
        # When both a query and an embedding adapter are present we run TRUE
        # hybrid retrieval: a lexical (BM25) ranking and a semantic (cosine)
        # ranking are computed over the same candidate set and fused with
        # Reciprocal Rank Fusion. This beats either signal alone and is why the
        # class is called "hybrid" — previously it used only one or the other.
        results_list: list[MemoryNode]
        node_list = list(candidates.values())
        if query and self.embeddings:
            results_list = self._hybrid_rank(query, node_list)
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

        Used when no embedding adapter is configured. Falls back to salience
        ordering if every score is zero (no term overlap).
        """
        if not nodes:
            return []
        scores = bm25_scores(query, nodes)
        if not scores or all(s == 0.0 for s in scores.values()):
            return sorted(
                nodes, key=lambda n: (n.salience, n.access_count), reverse=True
            )
        return sorted(
            nodes, key=lambda n: (scores.get(n.id, 0.0), n.salience), reverse=True
        )

    def _cosine_scores(self, query: str, nodes: list[MemoryNode]) -> dict[str, float]:
        """Cosine similarity of each node's embedding against the query.

        Embeds any missing node embeddings in a single batched call when the
        adapter supports ``embed_batch`` (falls back to per-node ``embed``).
        The computed embedding is written back onto the node so a subsequent
        query in the same process reuses it — the indexer owns the persistent
        cache, this is just an in-memory speedup.
        """
        q_emb = self.embeddings.embed(query)
        missing = [n for n in nodes if n.embedding is None]
        if missing:
            texts = [n.content or n.title for n in missing]
            embed_batch = getattr(self.embeddings, "embed_batch", None)
            if callable(embed_batch):
                vectors = embed_batch(texts)
            else:
                vectors = [self.embeddings.embed(t) for t in texts]
            for node, vec in zip(missing, vectors):
                node.embedding = vec
        return {n.id: self._cosine_similarity(q_emb, n.embedding or []) for n in nodes}

    def _hybrid_rank(self, query: str, nodes: list[MemoryNode]) -> list[MemoryNode]:
        """True hybrid ranking: fuse BM25 and cosine rankings with RRF.

        Falls back gracefully to whichever signal is available: if neither
        produces a signal, order by salience.
        """
        if not nodes:
            return []

        lex = bm25_scores(query, nodes)
        sem = self._cosine_scores(query, nodes)

        lex_ranking = [
            n.id for n in sorted(nodes, key=lambda n: lex.get(n.id, 0.0), reverse=True)
        ]
        sem_ranking = [
            n.id for n in sorted(nodes, key=lambda n: sem.get(n.id, 0.0), reverse=True)
        ]

        fused = reciprocal_rank_fusion([lex_ranking, sem_ranking])
        return sorted(
            nodes,
            key=lambda n: (fused.get(n.id, 0.0), n.salience),
            reverse=True,
        )

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
