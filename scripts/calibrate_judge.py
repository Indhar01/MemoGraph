#!/usr/bin/env python3
"""Calibrate the LLM judge against author scores on a stratified sample.

Two-step UX:
    1) python scripts/calibrate_judge.py --prepare
       Picks 30 stratified responses (10 per condition), writes them to
       paper/experimental_runs/calibration_template.json with placeholder
       human_scores. The condition is hidden behind a sample_id so scoring
       is blind.

    2) Open calibration_template.json, fill in `human_scores` for each item.

    3) python scripts/calibrate_judge.py --compute-kappa
       Reads the filled template, joins against judge_scores.jsonl on the
       (condition, query_idx) pair, and reports Cohen's kappa per dimension.
       Writes paper/experimental_runs/calibration.json.

The threshold for accepting LLM-judge scores on the remaining 180 items is
kappa >= 0.60 (substantial agreement) on at least the CRS dimension.
"""

from __future__ import annotations

import argparse
import json
import random
import sys

from _paper_eval_helpers import QUERIES_JSON, RUNS_DIR, QueriesDoc

CONDITIONS = ("baseline", "in_context", "memograph")
TEMPLATE_PATH = RUNS_DIR / "calibration_template.json"
JUDGE_SCORES_PATH = RUNS_DIR / "judge_scores.jsonl"
CALIBRATION_OUT = RUNS_DIR / "calibration.json"

DIMENSIONS = ("crs", "accuracy", "completeness", "personalization")
SAMPLES_PER_CONDITION = 10
SEED = 42


def load_logs(condition: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for p in sorted((RUNS_DIR / condition).glob("session_*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            out[entry["query_idx"]] = entry
    return out


def prepare() -> int:
    if not QUERIES_JSON.exists():
        sys.stderr.write(
            f"ERROR: {QUERIES_JSON} missing. Run parse + run_real_experiments first.\n"
        )
        return 2
    doc = QueriesDoc.from_json_path(QUERIES_JSON)
    logs = {c: load_logs(c) for c in CONDITIONS}

    rng = random.Random(SEED)
    items = []
    for cond in CONDITIONS:
        candidate_idxs = [
            q.idx
            for q in doc.all_queries()
            if q.idx in logs[cond] and logs[cond][q.idx].get("response_text")
        ]
        if len(candidate_idxs) < SAMPLES_PER_CONDITION:
            sys.stderr.write(
                f"WARNING: condition {cond} has only {len(candidate_idxs)} eligible responses "
                f"(want {SAMPLES_PER_CONDITION}). Continuing with what's available.\n"
            )
            sample = candidate_idxs
        else:
            sample = rng.sample(candidate_idxs, SAMPLES_PER_CONDITION)
        for q_idx in sample:
            log = logs[cond][q_idx]
            q_text = next((q.text for q in doc.all_queries() if q.idx == q_idx), "")
            items.append(
                {
                    "_condition_HIDDEN": cond,
                    "query_idx": q_idx,
                    "query_text": q_text,
                    "response_text": log["response_text"],
                    "human_scores": {d: None for d in DIMENSIONS},
                }
            )

    rng.shuffle(items)
    for i, it in enumerate(items, 1):
        it["sample_id"] = f"S{i:03d}"
    items_for_file = [
        {
            "sample_id": it["sample_id"],
            "query_text": it["query_text"],
            "response_text": it["response_text"],
            "human_scores": it["human_scores"],
            "_condition_HIDDEN": it["_condition_HIDDEN"],
            "_query_idx_HIDDEN": it["query_idx"],
        }
        for it in items
    ]

    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATE_PATH.write_text(
        json.dumps(items_for_file, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {TEMPLATE_PATH} with {len(items_for_file)} samples.")
    print(
        "Open it in your editor and fill `human_scores` for each item with integers 1-5."
    )
    print("Then run: python scripts/calibrate_judge.py --compute-kappa")
    return 0


def cohen_kappa_quadratic(
    y1: list[int], y2: list[int], min_v: int = 1, max_v: int = 5
) -> float:
    """Quadratic-weighted Cohen's kappa for ordinal scores."""
    n = len(y1)
    if n == 0:
        return float("nan")
    levels = list(range(min_v, max_v + 1))
    L = len(levels)
    obs = [[0] * L for _ in range(L)]
    for a, b in zip(y1, y2):
        a = max(min_v, min(max_v, int(a)))
        b = max(min_v, min(max_v, int(b)))
        obs[a - min_v][b - min_v] += 1
    row_totals = [sum(r) for r in obs]
    col_totals = [sum(obs[i][j] for i in range(L)) for j in range(L)]

    weights = [[((i - j) ** 2) / ((L - 1) ** 2) for j in range(L)] for i in range(L)]
    num = 0.0
    den = 0.0
    for i in range(L):
        for j in range(L):
            o = obs[i][j] / n
            e = (row_totals[i] / n) * (col_totals[j] / n)
            num += weights[i][j] * o
            den += weights[i][j] * e
    if den == 0:
        return float("nan")
    return 1.0 - num / den


def compute_kappa() -> int:
    if not TEMPLATE_PATH.exists():
        sys.stderr.write(f"ERROR: {TEMPLATE_PATH} missing. Run --prepare first.\n")
        return 2
    if not JUDGE_SCORES_PATH.exists():
        sys.stderr.write(
            f"ERROR: {JUDGE_SCORES_PATH} missing. Run score_experiments.py first.\n"
        )
        return 2

    items = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    judge_rows = []
    for line in JUDGE_SCORES_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            judge_rows.append(json.loads(line))

    judge_lookup: dict[tuple[str, int], dict] = {}
    for r in judge_rows:
        s = r.get("scores") or {}
        if "error" in s:
            continue
        judge_lookup[(r["condition"], r["query_idx"])] = s

    paired: dict[str, list[tuple[int, int]]] = {d: [] for d in DIMENSIONS}
    skipped = 0
    for it in items:
        cond = it["_condition_HIDDEN"]
        q_idx = it["_query_idx_HIDDEN"]
        judge = judge_lookup.get((cond, q_idx))
        if judge is None:
            skipped += 1
            continue
        human = it.get("human_scores", {})
        ok = all(isinstance(human.get(d), int) for d in DIMENSIONS)
        if not ok:
            skipped += 1
            continue
        for d in DIMENSIONS:
            paired[d].append((human[d], judge[d]))

    print(
        f"Paired {len(paired['crs'])} samples; skipped {skipped} (missing judge or human scores)."
    )

    out = {"per_dimension": {}, "n_paired": len(paired["crs"]), "n_skipped": skipped}
    for d in DIMENSIONS:
        h = [a for a, _ in paired[d]]
        j = [b for _, b in paired[d]]
        if len(h) < 5:
            print(f"  {d}: too few pairs ({len(h)})")
            out["per_dimension"][d] = None
            continue
        kappa = cohen_kappa_quadratic(h, j)
        n_exact = sum(1 for a, b in zip(h, j) if a == b)
        n_within1 = sum(1 for a, b in zip(h, j) if abs(a - b) <= 1)
        print(
            f"  {d}: n={len(h)}, kappa(quadratic)={kappa:.3f}, exact={n_exact}/{len(h)}, within1={n_within1}/{len(h)}"
        )
        out["per_dimension"][d] = {
            "kappa": round(kappa, 3),
            "n": len(h),
            "exact_match": n_exact,
            "within_one": n_within1,
        }

    crs = out["per_dimension"].get("crs") or {}
    out["passes_threshold"] = (crs.get("kappa") or 0.0) >= 0.60
    out["threshold"] = 0.60

    CALIBRATION_OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nWrote {CALIBRATION_OUT}")
    print(f"  CRS kappa >= 0.60? {out['passes_threshold']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--compute-kappa", action="store_true")
    args = ap.parse_args()
    if args.prepare and args.compute_kappa:
        ap.error("pick one of --prepare or --compute-kappa")
    if args.prepare:
        return prepare()
    if args.compute_kappa:
        return compute_kappa()
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
