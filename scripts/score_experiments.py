#!/usr/bin/env python3
"""Compute MRA, CSC, CRS, RQD and graph-quality metrics from per-session JSONL logs.

Inputs:
    paper/experimental_runs/queries.json
    paper/experimental_runs/{baseline,in_context,memograph}/session_NN.jsonl
    paper/experimental_runs/vaults/condition_c/                  (Condition C final vault)

Output:
    paper/experimental_results.json (overwritten in real-data schema)
    paper/experimental_runs/judge_scores.jsonl (per-response judge details)

Usage:
    python scripts/score_experiments.py                  # full scoring
    python scripts/score_experiments.py --skip-judge     # MRA, CSC, graph only (no API calls)
    python scripts/score_experiments.py --judge-limit N  # cap LLM-judge calls (smoke)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _paper_eval_helpers import (
    JUDGE_MODEL,
    PAPER_DIR,
    QUERIES_JSON,
    RUNS_DIR,
    QueriesDoc,
    Query,
    require_anthropic_key,
    write_json,
)

CONDITIONS = ("baseline", "in_context", "memograph")

# ---------------------------------------------------------------------------
# Loading logs.
# ---------------------------------------------------------------------------


def load_session_logs(condition: str) -> dict[int, list[dict]]:
    """Return {query_idx: log_dict} for one condition, across all sessions present."""
    out: dict[int, list[dict]] = {}
    for p in sorted((RUNS_DIR / condition).glob("session_*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            out.setdefault(entry["query_idx"], []).append(entry)
    return out


# ---------------------------------------------------------------------------
# MRA — Memory Retrieval Accuracy.
# ---------------------------------------------------------------------------


_GT_PREFIXES = (
    "user chose ",
    "user uses ",
    "user prefers ",
    "user implements ",
    "user aims for ",
    "user maintains ",
    "user follows ",
)


def gt_phrases(gt_titles: list[str]) -> list[str]:
    out: list[str] = []
    for raw in gt_titles:
        s = raw.lower().strip()
        for prefix in _GT_PREFIXES:
            if s.startswith(prefix):
                s = s[len(prefix) :]
                break
        s = re.sub(r"\(.*?\)", "", s).strip(" .;:,")
        if s and s.upper() != "N/A":
            out.append(s)
    return out


def haystack_match(haystack: str, phrases: list[str]) -> bool:
    if not phrases:
        return False
    h = haystack.lower()
    for p in phrases:
        if p and p in h:
            return True
        first = p.split()[0] if p.split() else ""
        if len(first) >= 3 and first in h:
            return True
    return False


def _baseline_mra_haystack(log: dict, query_text: str) -> str:
    return query_text


def _in_context_mra_haystack(log: dict) -> str:
    parts = []
    for ex in log.get("in_context_excerpts", []):
        parts.append(ex.get("query_text", ""))
        parts.append(ex.get("response_excerpt", ""))
    return "\n".join(parts)


def _memograph_mra_haystack(log: dict) -> str:
    parts = []
    for tc in log.get("tool_calls", []):
        if tc.get("tool") != "search_memories":
            continue
        for r in tc.get("results", []) or []:
            parts.append(r.get("title", ""))
            parts.append(r.get("snippet", ""))
    return "\n".join(parts)


def _is_leading(q: Query) -> bool:
    """True if the ground-truth phrase appears in the query text itself.
    These queries are answerable without any memory and inflate the baseline."""
    phrases = gt_phrases(q.ground_truth_titles)
    if not phrases:
        return False
    return haystack_match(q.text, phrases)


def compute_mra(
    doc: QueriesDoc, logs_by_cond: dict[str, dict[int, list[dict]]]
) -> dict:
    out = {}
    retrieval_queries = [q for q in doc.all_queries() if q.retrieval_required]
    total = len(retrieval_queries)
    leading = [q for q in retrieval_queries if _is_leading(q)]
    non_leading = [q for q in retrieval_queries if not _is_leading(q)]
    for cond in CONDITIONS:
        successes = 0
        successes_strict = 0
        per_query: list[dict] = []
        for q in retrieval_queries:
            phrases = gt_phrases(q.ground_truth_titles)
            log_list = logs_by_cond[cond].get(q.idx, [])
            if not log_list:
                per_query.append(
                    {"query_idx": q.idx, "matched": False, "reason": "no_log"}
                )
                continue
            log = log_list[-1]
            if cond == "baseline":
                hay = _baseline_mra_haystack(log, q.text)
            elif cond == "in_context":
                hay = _in_context_mra_haystack(log)
            else:
                hay = _memograph_mra_haystack(log)
            ok = haystack_match(hay, phrases)
            if ok:
                successes += 1
                if not _is_leading(q):
                    successes_strict += 1
            per_query.append(
                {"query_idx": q.idx, "matched": ok, "leading": _is_leading(q)}
            )
        pct = round(successes / total * 100, 1) if total else 0.0
        pct_strict = (
            round(successes_strict / len(non_leading) * 100, 1) if non_leading else 0.0
        )
        out[cond] = pct
        out[f"{cond}_strict"] = pct_strict
        out[f"{cond}_detail"] = {
            "successes": successes,
            "total": total,
            "successes_strict": successes_strict,
            "total_strict": len(non_leading),
            "per_query": per_query,
        }
    out["total_retrieval_queries"] = total
    out["leading_queries"] = len(leading)
    out["non_leading_queries"] = len(non_leading)
    return out


# ---------------------------------------------------------------------------
# CSC — Cross-Session Consistency.
# ---------------------------------------------------------------------------


def compute_csc(
    doc: QueriesDoc,
    logs_by_cond: dict[str, dict[int, list[dict]]],
    total_facts: int = 15,
) -> dict:
    """A CSC fact is CORRECT for a condition if at least one referencing query's response
    contains the ground-truth phrase. Out of `total_facts` (annotated count or 15)."""
    fact_to_queries: dict[int, list[Query]] = {}
    for q in doc.all_queries():
        if q.session_id < 6:
            continue
        for f in q.csc_facts:
            fact_to_queries.setdefault(f, []).append(q)

    annotated_facts = sorted(fact_to_queries.keys())
    out = {"annotated_facts": annotated_facts, "total_facts_in_paper": total_facts}
    for cond in CONDITIONS:
        correct = 0
        per_fact: list[dict] = []
        for fact_id, queries in fact_to_queries.items():
            recalled = False
            for q in queries:
                phrases = gt_phrases(q.ground_truth_titles)
                if not phrases:
                    continue
                logs = logs_by_cond[cond].get(q.idx, [])
                if not logs:
                    continue
                response = logs[-1].get("response_text", "") or ""
                if haystack_match(response, phrases):
                    recalled = True
                    break
            if recalled:
                correct += 1
            per_fact.append(
                {
                    "fact_id": fact_id,
                    "recalled": recalled,
                    "queries": [q.idx for q in queries],
                }
            )
        out[cond] = correct
        out[f"{cond}_total"] = total_facts
        out[f"{cond}_per_fact"] = per_fact
    return out


# ---------------------------------------------------------------------------
# Graph quality — Condition C vault introspection.
# ---------------------------------------------------------------------------


WIKILINK_RE = re.compile(r"\[\[([^\]\|]+?)(?:\|[^\]]+)?\]\]")


def compute_graph_quality(logs_by_cond: dict[str, dict[int, list[dict]]]) -> dict:
    """Inspect the Condition C vault and the create_memory tool calls to compute
    suggestion / acceptance / connectivity metrics."""
    vault_root = RUNS_DIR / "vaults" / "condition_c"

    total_suggestions = 0
    accepted_links = 0
    title_to_normalized: dict[str, str] = {}

    md_files = list(vault_root.glob("*.md")) if vault_root.exists() else []
    for p in md_files:
        text = p.read_text(encoding="utf-8")
        m = re.search(r"^title:\s*(.+)$", text, re.M)
        title = (m.group(1).strip().strip('"') if m else p.stem).lower()
        title_to_normalized[title] = title

    total_memories = len(md_files)
    in_degree: dict[str, int] = {t: 0 for t in title_to_normalized}
    out_degree: dict[str, int] = {t: 0 for t in title_to_normalized}

    for p in md_files:
        text = p.read_text(encoding="utf-8")
        body = text.split("---", 2)[-1] if text.startswith("---") else text
        m = re.search(r"^title:\s*(.+)$", text, re.M)
        src_title = (m.group(1).strip().strip('"') if m else p.stem).lower()
        for link_match in WIKILINK_RE.finditer(body):
            target = link_match.group(1).strip().lower()
            total_suggestions += 1
            if target in title_to_normalized:
                accepted_links += 1
                in_degree[title_to_normalized[target]] = (
                    in_degree.get(title_to_normalized[target], 0) + 1
                )
                out_degree[src_title] = out_degree.get(src_title, 0) + 1

    acceptance_rate = (
        round(accepted_links / total_suggestions * 100, 1) if total_suggestions else 0.0
    )

    degrees = []
    isolated = 0
    for t in title_to_normalized:
        d = in_degree.get(t, 0) + out_degree.get(t, 0)
        degrees.append(d)
        if d == 0:
            isolated += 1
    avg_degree = round(sum(degrees) / len(degrees), 2) if degrees else 0.0
    max_degree = max(degrees) if degrees else 0
    isolation_pct = round(isolated / total_memories * 100, 1) if total_memories else 0.0
    total_connections = sum(out_degree.values())

    queries_with_search_results = 0
    queries_enriched = 0
    for q_idx, log_list in logs_by_cond["memograph"].items():
        for log in log_list:
            search_results_seen = False
            for tc in log.get("tool_calls", []):
                if tc.get("tool") == "search_memories" and tc.get("results"):
                    search_results_seen = True
                    if len(tc["results"]) >= 2:
                        queries_enriched += 1
                        break
            if search_results_seen:
                queries_with_search_results += 1
                break
    enrichment_rate = (
        round(queries_enriched / queries_with_search_results * 100, 1)
        if queries_with_search_results
        else 0.0
    )

    total_turns = 0
    successful_hooks = 0
    for q_idx, log_list in logs_by_cond["memograph"].items():
        for log in log_list:
            total_turns += 1
            for tc in log.get("tool_calls", []):
                if tc.get("tool") == "create_memory" and not tc.get("error"):
                    successful_hooks += 1
                    break
    auto_save_compliance = (
        round(successful_hooks / total_turns * 100, 1) if total_turns else 0.0
    )

    return {
        "total_suggestions": total_suggestions,
        "accepted_links": accepted_links,
        "acceptance_rate": acceptance_rate,
        "enriched_queries": queries_enriched,
        "total_queries_with_matches": queries_with_search_results,
        "enrichment_rate": enrichment_rate,
        "total_memories": total_memories,
        "isolated_nodes": isolated,
        "isolation_percentage": isolation_pct,
        "total_connections": total_connections,
        "avg_node_degree": avg_degree,
        "max_node_degree": max_degree,
        "auto_save_compliance": auto_save_compliance,
    }


# ---------------------------------------------------------------------------
# CRS + RQD — LLM-as-judge.
# ---------------------------------------------------------------------------


JUDGE_SYSTEM = """You are an impartial evaluator scoring an AI assistant's response quality.

For each response, you will see:
  - A user query
  - The AI assistant's response

Score on the following 1-5 scales (integer scores only):

CRS (Context Relevance) - How relevant was any context the response drew on?
  5 = Highly relevant, directly enables a complete answer.
  4 = Mostly relevant, minor gaps.
  3 = Partially relevant, significant gaps.
  2 = Minimally relevant, mostly tangential.
  1 = Completely irrelevant or no context where context was clearly needed.

ACCURACY - Is the information correct?
  5 = Completely accurate. 4 = Mostly. 3 = Partially. 2 = Mostly inaccurate. 1 = Completely inaccurate.

COMPLETENESS - Does it fully answer the question?
  5 = Fully complete. 4 = Mostly. 3 = Partially. 2 = Mostly incomplete. 1 = Fails to address query.

PERSONALIZATION - Is it tailored to the user's specific context, decisions, and prior preferences?
  5 = Highly personalized; references specific user context.
  4 = Mostly personalized.
  3 = Some personalization, mostly generic.
  2 = Minimal personalization.
  1 = Completely generic.

You MUST return a single JSON object on one line, no prose, no code fences:
{"crs": <1-5>, "accuracy": <1-5>, "completeness": <1-5>, "personalization": <1-5>}
"""


def _judge_one(client, query_text: str, response_text: str) -> dict | None:
    if not response_text.strip():
        return {
            "crs": 1,
            "accuracy": 1,
            "completeness": 1,
            "personalization": 1,
            "error": "empty_response",
        }
    user = (
        f"USER QUERY:\n{query_text}\n\n"
        f"AI RESPONSE:\n{response_text}\n\n"
        "Return the JSON object now."
    )
    try:
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=128,
            system=[
                {
                    "type": "text",
                    "text": JUDGE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}

    text = ""
    for b in resp.content:
        if getattr(b, "type", None) == "text":
            text += b.text
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"error": "no_json", "raw": text[:200]}
    try:
        scores = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"error": "bad_json", "raw": text[:200]}
    for k in ("crs", "accuracy", "completeness", "personalization"):
        if k not in scores:
            return {"error": f"missing_{k}", "raw": text[:200]}
        v = scores[k]
        scores[k] = max(1, min(5, int(v))) if isinstance(v, (int, float)) else 1
    return scores


def run_judge(
    doc: QueriesDoc,
    logs_by_cond: dict[str, dict[int, list[dict]]],
    *,
    limit: int | None = None,
    out_path: Path | None = None,
):
    require_anthropic_key()
    import anthropic

    client = anthropic.Anthropic()

    items: list[tuple[str, Query, str]] = []
    for cond in CONDITIONS:
        for q in doc.all_queries():
            log = logs_by_cond[cond].get(q.idx, [])
            if not log:
                continue
            items.append((cond, q, log[-1].get("response_text", "") or ""))

    if limit is not None:
        items = items[:limit]

    print(f"Running judge on {len(items)} responses ({JUDGE_MODEL})...")
    rows: list[dict] = []
    for i, (cond, q, resp) in enumerate(items, 1):
        scores = _judge_one(client, q.text, resp)
        row = {
            "condition": cond,
            "query_idx": q.idx,
            "session_id": q.session_id,
            "scores": scores,
        }
        rows.append(row)
        if i % 10 == 0 or i == len(items):
            print(f"  judged {i}/{len(items)}")

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def aggregate_judge(rows: list[dict]) -> dict:
    by_cond: dict[str, list[dict]] = {c: [] for c in CONDITIONS}
    for r in rows:
        s = r.get("scores") or {}
        if "error" in s:
            continue
        if r["condition"] in by_cond:
            by_cond[r["condition"]].append(s)

    def _mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    crs_out: dict = {}
    rqd_out: dict = {}
    quality_per_cond: dict[str, float] = {}

    for cond in CONDITIONS:
        crs_vals = [s["crs"] for s in by_cond[cond]]
        crs_out[cond] = round(_mean(crs_vals), 2)
        quality = [
            (s["accuracy"] + s["completeness"] + s["personalization"]) / 3
            for s in by_cond[cond]
        ]
        quality_per_cond[cond] = _mean(quality)

    baseline_q = quality_per_cond.get("baseline", 0.0)
    rqd_out["baseline"] = 0.0
    rqd_out["in_context"] = round(
        quality_per_cond.get("in_context", 0.0) - baseline_q, 2
    )
    rqd_out["memograph"] = round(quality_per_cond.get("memograph", 0.0) - baseline_q, 2)
    rqd_out["_quality_means"] = {k: round(v, 2) for k, v in quality_per_cond.items()}

    return {
        "crs": crs_out,
        "rqd": rqd_out,
        "n_per_condition": {c: len(by_cond[c]) for c in CONDITIONS},
    }


# ---------------------------------------------------------------------------
# Top-level orchestration.
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--skip-judge",
        action="store_true",
        help="skip CRS/RQD; deterministic metrics only",
    )
    ap.add_argument(
        "--judge-limit", type=int, default=None, help="cap judge calls (smoke)"
    )
    ap.add_argument(
        "--total-facts", type=int, default=15, help="denominator for CSC X/N"
    )
    ap.add_argument("--out", type=Path, default=PAPER_DIR / "experimental_results.json")
    args = ap.parse_args()

    if not QUERIES_JSON.exists():
        sys.stderr.write(f"ERROR: {QUERIES_JSON} missing.\n")
        return 2

    doc = QueriesDoc.from_json_path(QUERIES_JSON)
    logs_by_cond = {c: load_session_logs(c) for c in CONDITIONS}

    print("Computing MRA...")
    mra = compute_mra(doc, logs_by_cond)
    print(
        f"  MRA (lenient, n={mra['total_retrieval_queries']}): "
        f"{mra['baseline']}% / {mra['in_context']}% / {mra['memograph']}%"
    )
    print(
        f"  MRA (strict, excludes {mra['leading_queries']} leading queries, n={mra['non_leading_queries']}): "
        f"{mra['baseline_strict']}% / {mra['in_context_strict']}% / {mra['memograph_strict']}%"
    )

    print("Computing CSC...")
    csc = compute_csc(doc, logs_by_cond, total_facts=args.total_facts)
    print(
        f"  CSC: {csc['baseline']}/{args.total_facts} / {csc['in_context']}/{args.total_facts} / {csc['memograph']}/{args.total_facts}"
    )

    print("Computing graph quality...")
    graph = compute_graph_quality(logs_by_cond)
    print(
        f"  Graph: total_memories={graph['total_memories']}, suggestions={graph['total_suggestions']}, accepted={graph['accepted_links']} ({graph['acceptance_rate']}%)"
    )

    if args.skip_judge:
        crs = {"baseline": 0.0, "in_context": 0.0, "memograph": 0.0, "_skipped": True}
        rqd = {"baseline": 0.0, "in_context": 0.0, "memograph": 0.0, "_skipped": True}
        print("Skipping CRS/RQD (--skip-judge).")
    else:
        rows = run_judge(
            doc,
            logs_by_cond,
            limit=args.judge_limit,
            out_path=RUNS_DIR / "judge_scores.jsonl",
        )
        agg = aggregate_judge(rows)
        crs = agg["crs"]
        rqd = agg["rqd"]
        print(f"  CRS: {crs}")
        print(f"  RQD: {rqd}")

    out = {
        "mra": {
            "baseline": mra["baseline"],
            "in_context": mra["in_context"],
            "memograph": mra["memograph"],
        },
        "mra_strict": {
            "baseline": mra["baseline_strict"],
            "in_context": mra["in_context_strict"],
            "memograph": mra["memograph_strict"],
            "n_leading_queries": mra["leading_queries"],
            "n_non_leading": mra["non_leading_queries"],
        },
        "crs": crs,
        "csc": {
            "baseline": csc["baseline"],
            "baseline_total": args.total_facts,
            "in_context": csc["in_context"],
            "in_context_total": args.total_facts,
            "memograph": csc["memograph"],
            "memograph_total": args.total_facts,
        },
        "rqd": {
            "baseline": rqd["baseline"],
            "in_context": rqd["in_context"],
            "memograph": rqd["memograph"],
        },
        "graph": graph,
        "_meta": {
            "generator_model": "claude-sonnet-4-6",
            "judge_model": JUDGE_MODEL,
            "csc_annotated_facts": csc.get("annotated_facts"),
        },
    }
    write_json(args.out, out)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
