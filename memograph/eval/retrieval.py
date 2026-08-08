"""Deterministic, LLM-free retrieval evaluation harness.

This is intentionally SEPARATE from the paper's LLM-judged benchmark
(MRA / CRS via Claude judges; see BENCHMARKS.md and benchmarks/README.md,
which asks contributors NOT to fork that pipeline). This module measures a
different, complementary thing: **retrieval ranking quality** — given a query
and a set of known-relevant note ids, does the retriever rank them highly? —
using classic IR metrics that run offline in milliseconds with no model calls.

Use it in CI to guard against ranking regressions when changing retrieval
(seeds, fusion, graph blend, ...). It does NOT measure answer quality; the
LLM-judged pipeline owns that.

Gold set format (JSON list)::

    [
      {"query": "dependency injection", "relevant_ids": ["fastapi-dependencies"]},
      {"query": "async patterns", "relevant_ids": ["python-async", "async-pitfalls"]}
    ]

Optional per-case keys: ``tags`` (list[str]) and ``top_k`` (int) override the
run defaults for that case.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid a hard import cycle / heavy import at module load
    from memograph.core.kernel import MemoryKernel


# --------------------------------------------------------------------- metrics
# All metrics take the RANKED list of retrieved ids and the SET of relevant ids.
# They are pure functions — trivially unit-testable and dependency-free.


def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = ranked[:k]
    if not top:
        return 0.0
    hits = sum(1 for r in top if r in relevant)
    return hits / len(top)


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for r in ranked[:k] if r in relevant)
    return hits / len(relevant)


def f1_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    p = precision_at_k(ranked, relevant, k)
    r = recall_at_k(ranked, relevant, k)
    if p + r == 0.0:
        return 0.0
    return 2 * p * r / (p + r)


def hit_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """1.0 if any relevant id appears in the top-k, else 0.0."""
    return 1.0 if any(r in relevant for r in ranked[:k]) else 0.0


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    """1 / rank of the first relevant id (1-based); 0 if none found."""
    for i, r in enumerate(ranked, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Binary-relevance nDCG@k."""
    dcg = 0.0
    for i, r in enumerate(ranked[:k], start=1):
        if r in relevant:
            dcg += 1.0 / math.log2(i + 1)
    ideal_hits = min(len(relevant), k)
    if ideal_hits == 0:
        return 0.0
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


# ---------------------------------------------------------------- data classes


@dataclass
class GoldCase:
    query: str
    relevant_ids: set[str]
    tags: list[str] | None = None
    top_k: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoldCase:
        query = data.get("query")
        if not query or not isinstance(query, str):
            raise ValueError("gold case requires a non-empty 'query' string")
        relevant = data.get("relevant_ids") or data.get("relevant") or []
        if not isinstance(relevant, list):
            raise ValueError(f"'relevant_ids' must be a list for query {query!r}")
        return cls(
            query=query,
            relevant_ids={str(r).lower().replace(" ", "-") for r in relevant},
            tags=data.get("tags"),
            top_k=data.get("top_k"),
        )


@dataclass
class CaseResult:
    query: str
    retrieved_ids: list[str]
    relevant_ids: set[str]
    metrics: dict[str, float]


@dataclass
class EvalReport:
    k: int
    cases: list[CaseResult] = field(default_factory=list)
    aggregate: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "num_cases": len(self.cases),
            "aggregate": self.aggregate,
            "cases": [
                {
                    "query": c.query,
                    "retrieved_ids": c.retrieved_ids,
                    "relevant_ids": sorted(c.relevant_ids),
                    "metrics": c.metrics,
                }
                for c in self.cases
            ],
        }


# --------------------------------------------------------------------- loaders


def load_gold_set(path: str | Path) -> list[GoldCase]:
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, dict) and "cases" in data:
        data = data["cases"]
    if not isinstance(data, list):
        raise ValueError("gold set must be a JSON list (or {'cases': [...]})")
    return [GoldCase.from_dict(item) for item in data]


# --------------------------------------------------------------------- harness


def _metrics_for_case(
    ranked: list[str], relevant: set[str], k: int
) -> dict[str, float]:
    return {
        f"precision@{k}": precision_at_k(ranked, relevant, k),
        f"recall@{k}": recall_at_k(ranked, relevant, k),
        f"f1@{k}": f1_at_k(ranked, relevant, k),
        f"hit@{k}": hit_at_k(ranked, relevant, k),
        f"ndcg@{k}": ndcg_at_k(ranked, relevant, k),
        "mrr": reciprocal_rank(ranked, relevant),
    }


def evaluate_retrieval(
    kernel: "MemoryKernel",
    gold: list[GoldCase],
    top_k: int = 8,
    depth: int = 2,
) -> EvalReport:
    """Run every gold case through ``kernel.retrieve_nodes`` and score it.

    Metrics are averaged (macro) across cases into ``report.aggregate``.
    Caching is disabled so each case reflects the current retriever state.
    """
    report = EvalReport(k=top_k)
    for case in gold:
        k = case.top_k or top_k
        nodes = kernel.retrieve_nodes(
            query=case.query,
            tags=case.tags,
            depth=depth,
            top_k=k,
            use_cache=False,
        )
        ranked = [n.id for n in nodes]
        metrics = _metrics_for_case(ranked, case.relevant_ids, k)
        report.cases.append(
            CaseResult(
                query=case.query,
                retrieved_ids=ranked,
                relevant_ids=case.relevant_ids,
                metrics=metrics,
            )
        )

    if report.cases:
        keys = report.cases[0].metrics.keys()
        report.aggregate = {
            key: sum(c.metrics[key] for c in report.cases) / len(report.cases)
            for key in keys
        }
    return report


__all__ = [
    "GoldCase",
    "CaseResult",
    "EvalReport",
    "load_gold_set",
    "evaluate_retrieval",
    "precision_at_k",
    "recall_at_k",
    "f1_at_k",
    "hit_at_k",
    "reciprocal_rank",
    "ndcg_at_k",
]
