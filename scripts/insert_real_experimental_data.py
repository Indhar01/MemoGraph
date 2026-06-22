#!/usr/bin/env python3
"""Replace the synthetic numbers and methodology disclaimers in paper/05_evaluation.md
with values from a real experimental run.

Reads:
    paper/experimental_results.json                       (real, schema same as synthetic)
    paper/experimental_runs/judge_scores.jsonl            (per-response judge details, optional)
    paper/experimental_runs/calibration.json              (Cohen's kappa, optional)
    paper/experimental_runs/_synthetic_results.json       (if present, used as the source of OLD strings to replace; otherwise we reconstruct from scripts/generate_synthetic_experimental_data.py)

Writes:
    paper/05_evaluation.md (in place)

Usage:
    python scripts/insert_real_experimental_data.py
    python scripts/insert_real_experimental_data.py --dry-run     # print diff, do not write
    python scripts/insert_real_experimental_data.py --old <path>  # explicit old JSON
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from _paper_eval_helpers import PAPER_DIR, RUNS_DIR

EVAL_MD = PAPER_DIR / "05_evaluation.md"
NEW_RESULTS = PAPER_DIR / "experimental_results.json"
JUDGE_SCORES = RUNS_DIR / "judge_scores.jsonl"
CALIBRATION = RUNS_DIR / "calibration.json"
SYNTHETIC_BACKUP = RUNS_DIR / "_synthetic_results.json"


SYNTHETIC_FALLBACK = {
    "mra": {"baseline": 15.4, "in_context": 59.6, "memograph": 82.7},
    "crs": {"baseline": 1.68, "in_context": 3.39, "memograph": 4.12},
    "csc": {
        "baseline": 2,
        "in_context": 11,
        "memograph": 13,
        "baseline_total": 15,
        "in_context_total": 15,
        "memograph_total": 15,
    },
    "rqd": {"baseline": 0.0, "in_context": 1.2, "memograph": 2.0},
    "graph": {
        "total_suggestions": 46,
        "accepted_links": 34,
        "acceptance_rate": 74.5,
        "enriched_queries": 40,
        "total_queries_with_matches": 54,
        "enrichment_rate": 74.5,
        "total_memories": 67,
        "isolated_nodes": 5,
        "isolation_percentage": 7.5,
        "total_connections": 197,
        "avg_node_degree": 2.94,
        "max_node_degree": 10,
        "auto_save_compliance": 85.6,
    },
}


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, (center - margin)) * 100, min(1.0, (center + margin)) * 100)


def t_margin(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n < 2:
        return (0.0, 0.0)
    m = sum(values) / n
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    sd = math.sqrt(var)
    half = 1.96 * sd / math.sqrt(n)
    return (round(m, 2), round(half, 2))


def load_judge_per_condition() -> dict:
    """Returns {cond: {dim: [scores]}} from judge_scores.jsonl."""
    out: dict = {}
    if not JUDGE_SCORES.exists():
        return out
    for line in JUDGE_SCORES.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        s = r.get("scores") or {}
        if "error" in s:
            continue
        cond = r["condition"]
        d = out.setdefault(
            cond, {"crs": [], "accuracy": [], "completeness": [], "personalization": []}
        )
        for k in ("crs", "accuracy", "completeness", "personalization"):
            if k in s:
                d[k].append(int(s[k]))
    return out


def fmt_pct(v: float) -> str:
    return f"{v:.1f}"


def fmt_score(v: float) -> str:
    return f"{v:.2f}"


def safe_replace(
    text: str, old: str, new: str, *, required: bool = True, label: str = ""
) -> tuple[str, int]:
    if old == new:
        return text, 0
    count = text.count(old)
    if count == 0:
        if required:
            sys.stderr.write(
                f"WARNING: replacement not found ({label}): {old[:80]!r}\n"
            )
        return text, 0
    return text.replace(old, new), count


def build_replacements(
    old: dict, new: dict, judge: dict, calibration: dict | None
) -> list[tuple[str, str, str]]:
    """Returns list of (old_str, new_str, label) replacements to apply in order."""
    rs: list[tuple[str, str, str]] = []

    n_mra = 52
    o_mra = old["mra"]
    n_mra_new = new["mra"]
    bl_lo, bl_hi = wilson_ci(int(round(n_mra_new["baseline"] / 100 * n_mra)), n_mra)
    ic_lo, ic_hi = wilson_ci(int(round(n_mra_new["in_context"] / 100 * n_mra)), n_mra)
    mg_lo, mg_hi = wilson_ci(int(round(n_mra_new["memograph"] / 100 * n_mra)), n_mra)

    rs.append(
        (
            f"**{o_mra['memograph']}%**",
            f"**{fmt_pct(n_mra_new['memograph'])}%**",
            "mra.memograph bold",
        )
    )
    rs.append(
        (
            f"**{o_mra['in_context']}%**",
            f"**{fmt_pct(n_mra_new['in_context'])}%**",
            "mra.in_context bold",
        )
    )
    rs.append(
        (
            f"**{o_mra['baseline']}%**",
            f"**{fmt_pct(n_mra_new['baseline'])}%**",
            "mra.baseline bold",
        )
    )

    rs.append(
        ("[7.8%, 27.9%]", f"[{fmt_pct(bl_lo)}%, {fmt_pct(bl_hi)}%]", "mra.baseline CI")
    )
    rs.append(
        (
            "[46.3%, 71.7%]",
            f"[{fmt_pct(ic_lo)}%, {fmt_pct(ic_hi)}%]",
            "mra.in_context CI",
        )
    )
    rs.append(
        (
            "[70.6%, 90.6%]",
            f"[{fmt_pct(mg_lo)}%, {fmt_pct(mg_hi)}%]",
            "mra.memograph CI",
        )
    )

    rs.append(
        (
            "15.4 [7.8, 27.9]",
            f"{fmt_pct(n_mra_new['baseline'])} [{fmt_pct(bl_lo)}, {fmt_pct(bl_hi)}]",
            "table1 mra baseline",
        )
    )
    rs.append(
        (
            "59.6 [46.3, 71.7]",
            f"{fmt_pct(n_mra_new['in_context'])} [{fmt_pct(ic_lo)}, {fmt_pct(ic_hi)}]",
            "table1 mra in_context",
        )
    )
    rs.append(
        (
            "82.7 [70.6, 90.6]",
            f"{fmt_pct(n_mra_new['memograph'])} [{fmt_pct(mg_lo)}, {fmt_pct(mg_hi)}]",
            "table1 mra memograph",
        )
    )

    rs.append(
        (
            "[7.8%, 27.9%] | Wilson score (n=52)",
            f"[{fmt_pct(bl_lo)}%, {fmt_pct(bl_hi)}%] | Wilson score (n={n_mra})",
            "table2 mra baseline",
        )
    )
    rs.append(
        (
            "[46.3%, 71.7%] | Wilson score (n=52)",
            f"[{fmt_pct(ic_lo)}%, {fmt_pct(ic_hi)}%] | Wilson score (n={n_mra})",
            "table2 mra in_context",
        )
    )
    rs.append(
        (
            "[70.6%, 90.6%] | Wilson score (n=52)",
            f"[{fmt_pct(mg_lo)}%, {fmt_pct(mg_hi)}%] | Wilson score (n={n_mra})",
            "table2 mra memograph",
        )
    )

    o_crs = old["crs"]
    n_crs = new["crs"]

    crs_means: dict[str, tuple[float, float]] = {}
    for cond, label in (
        ("baseline", "Baseline"),
        ("in_context", "In-Context"),
        ("memograph", "MemoGraph"),
    ):
        scores = (judge.get(cond) or {}).get("crs", [])
        if scores:
            mean, half = t_margin([float(x) for x in scores])
            crs_means[cond] = (mean, half)
        else:
            crs_means[cond] = (n_crs[cond], 0.0)

    rs.append(
        (
            f"**{o_crs['memograph']} +/- 0.19**",
            f"**{fmt_score(crs_means['memograph'][0])} +/- {fmt_score(crs_means['memograph'][1])}**",
            "crs memograph bold",
        )
    )
    rs.append(
        (
            f"**{o_crs['in_context']} +/- 0.19**",
            f"**{fmt_score(crs_means['in_context'][0])} +/- {fmt_score(crs_means['in_context'][1])}**",
            "crs in_context bold",
        )
    )
    rs.append(
        (
            f"**{o_crs['baseline']} +/- 0.19**",
            f"**{fmt_score(crs_means['baseline'][0])} +/- {fmt_score(crs_means['baseline'][1])}**",
            "crs baseline bold",
        )
    )

    rs.append(
        (
            f"| {o_crs['baseline']} +/- 0.19 |",
            f"| {fmt_score(crs_means['baseline'][0])} +/- {fmt_score(crs_means['baseline'][1])} |",
            "table1 crs baseline",
        )
    )
    rs.append(
        (
            f"| {o_crs['in_context']} +/- 0.19 |",
            f"| {fmt_score(crs_means['in_context'][0])} +/- {fmt_score(crs_means['in_context'][1])} |",
            "table1 crs in_context",
        )
    )
    rs.append(
        (
            f"| {o_crs['memograph']} +/- 0.19 |",
            f"| {fmt_score(crs_means['memograph'][0])} +/- {fmt_score(crs_means['memograph'][1])} |",
            "table1 crs memograph",
        )
    )

    n_bl_crs = max(len((judge.get("baseline") or {}).get("crs", [])), 1)
    n_ic_crs = max(len((judge.get("in_context") or {}).get("crs", [])), 1)
    n_mg_crs = max(len((judge.get("memograph") or {}).get("crs", [])), 1)
    rs.append(
        (
            "CRS | Baseline (A) | 1.68 | +/- 0.19 | t-interval (SD=0.3, n=10)",
            f"CRS | Baseline (A) | {fmt_score(crs_means['baseline'][0])} | +/- {fmt_score(crs_means['baseline'][1])} | t-interval (n={n_bl_crs})",
            "table2 crs baseline",
        )
    )
    rs.append(
        (
            "CRS | In-Context (B) | 3.39 | +/- 0.19 | t-interval (SD=0.3, n=10)",
            f"CRS | In-Context (B) | {fmt_score(crs_means['in_context'][0])} | +/- {fmt_score(crs_means['in_context'][1])} | t-interval (n={n_ic_crs})",
            "table2 crs in_context",
        )
    )
    rs.append(
        (
            "CRS | MemoGraph (C) | 4.12 | +/- 0.19 | t-interval (SD=0.3, n=10)",
            f"CRS | MemoGraph (C) | {fmt_score(crs_means['memograph'][0])} | +/- {fmt_score(crs_means['memograph'][1])} | t-interval (n={n_mg_crs})",
            "table2 crs memograph",
        )
    )

    o_csc = old["csc"]
    n_csc = new["csc"]
    n_total = n_csc.get("memograph_total", 15)
    bl_p = n_csc["baseline"] / n_total * 100
    ic_p = n_csc["in_context"] / n_total * 100
    mg_p = n_csc["memograph"] / n_total * 100
    bl_p_lo, bl_p_hi = wilson_ci(n_csc["baseline"], n_total)
    ic_p_lo, ic_p_hi = wilson_ci(n_csc["in_context"], n_total)
    mg_p_lo, mg_p_hi = wilson_ci(n_csc["memograph"], n_total)

    rs.append(
        (
            f"recalled **{o_csc['memograph']}** out of 15",
            f"recalled **{n_csc['memograph']}** out of {n_total}",
            "csc memograph count",
        )
    )
    rs.append(
        (
            f"compared to **{o_csc['in_context']}** for in-context memory",
            f"compared to **{n_csc['in_context']}** for in-context memory",
            "csc in_context count",
        )
    )
    rs.append(
        (
            f"and **{o_csc['baseline']}** for the baseline",
            f"and **{n_csc['baseline']}** for the baseline",
            "csc baseline count",
        )
    )

    bl_old_p = round(o_csc["baseline"] / 15 * 100, 1)
    ic_old_p = round(o_csc["in_context"] / 15 * 100, 1)
    mg_old_p = round(o_csc["memograph"] / 15 * 100, 1)
    rs.append(
        (f"CSC = **{bl_old_p}%**", f"CSC = **{fmt_pct(bl_p)}%**", "csc baseline pct")
    )
    rs.append(
        (f"CSC = **{ic_old_p}%**", f"CSC = **{fmt_pct(ic_p)}%**", "csc in_context pct")
    )
    rs.append(
        (f"CSC = **{mg_old_p}%**", f"CSC = **{fmt_pct(mg_p)}%**", "csc memograph pct")
    )

    rs.append(
        (
            "[2.3%, 38.0%]",
            f"[{fmt_pct(bl_p_lo)}%, {fmt_pct(bl_p_hi)}%]",
            "csc baseline CI",
        )
    )
    rs.append(
        (
            "[48.0%, 89.1%]",
            f"[{fmt_pct(ic_p_lo)}%, {fmt_pct(ic_p_hi)}%]",
            "csc in_context CI",
        )
    )
    rs.append(
        (
            "[62.1%, 96.3%]",
            f"[{fmt_pct(mg_p_lo)}%, {fmt_pct(mg_p_hi)}%]",
            "csc memograph CI",
        )
    )

    rs.append(
        (
            "13.3 [2.3, 38.0]",
            f"{fmt_pct(bl_p)} [{fmt_pct(bl_p_lo)}, {fmt_pct(bl_p_hi)}]",
            "table1 csc baseline",
        )
    )
    rs.append(
        (
            "73.3 [48.0, 89.1]",
            f"{fmt_pct(ic_p)} [{fmt_pct(ic_p_lo)}, {fmt_pct(ic_p_hi)}]",
            "table1 csc in_context",
        )
    )
    rs.append(
        (
            "86.7 [62.1, 96.3]",
            f"{fmt_pct(mg_p)} [{fmt_pct(mg_p_lo)}, {fmt_pct(mg_p_hi)}]",
            "table1 csc memograph",
        )
    )

    rs.append(
        (
            "CSC | Baseline (A) | 13.3% | [2.3%, 38.0%] | Wilson score (n=15)",
            f"CSC | Baseline (A) | {fmt_pct(bl_p)}% | [{fmt_pct(bl_p_lo)}%, {fmt_pct(bl_p_hi)}%] | Wilson score (n={n_total})",
            "table2 csc baseline",
        )
    )
    rs.append(
        (
            "CSC | In-Context (B) | 73.3% | [48.0%, 89.1%] | Wilson score (n=15)",
            f"CSC | In-Context (B) | {fmt_pct(ic_p)}% | [{fmt_pct(ic_p_lo)}%, {fmt_pct(ic_p_hi)}%] | Wilson score (n={n_total})",
            "table2 csc in_context",
        )
    )
    rs.append(
        (
            "CSC | MemoGraph (C) | 86.7% | [62.1%, 96.3%] | Wilson score (n=15)",
            f"CSC | MemoGraph (C) | {fmt_pct(mg_p)}% | [{fmt_pct(mg_p_lo)}%, {fmt_pct(mg_p_hi)}%] | Wilson score (n={n_total})",
            "table2 csc memograph",
        )
    )

    o_rqd = old["rqd"]
    quality_per_cond: dict[str, tuple[float, float]] = {}
    for cond in ("baseline", "in_context", "memograph"):
        scores = judge.get(cond) or {}
        a = scores.get("accuracy", [])
        c = scores.get("completeness", [])
        p = scores.get("personalization", [])
        if a and c and p:
            qvals = [
                (a[i] + c[i] + p[i]) / 3 for i in range(min(len(a), len(c), len(p)))
            ]
            quality_per_cond[cond] = t_margin(qvals)
        else:
            quality_per_cond[cond] = (0.0, 0.0)

    bq_mean, _ = quality_per_cond.get("baseline", (0.0, 0.0))
    ic_mean, ic_half = quality_per_cond.get("in_context", (0.0, 0.0))
    mg_mean, mg_half = quality_per_cond.get("memograph", (0.0, 0.0))
    ic_delta = ic_mean - bq_mean
    mg_delta = mg_mean - bq_mean

    rs.append(
        (
            f"**+{o_rqd['memograph']} +/- 0.12**",
            f"**{mg_delta:+.2f} +/- {mg_half:.2f}**",
            "rqd memograph bold",
        )
    )
    rs.append(
        (
            f"**+{o_rqd['in_context']} +/- 0.12**",
            f"**{ic_delta:+.2f} +/- {ic_half:.2f}**",
            "rqd in_context bold",
        )
    )

    rs.append(
        (
            f"| +{o_rqd['in_context']} +/- 0.12 | +{o_rqd['memograph']} +/- 0.12 |",
            f"| {ic_delta:+.2f} +/- {ic_half:.2f} | {mg_delta:+.2f} +/- {mg_half:.2f} |",
            "table1 rqd",
        )
    )
    n_ic_rqd = len((judge.get("in_context") or {}).get("accuracy", []))
    n_mg_rqd = len((judge.get("memograph") or {}).get("accuracy", []))
    rs.append(
        (
            f"RQD | In-Context (B) | +{o_rqd['in_context']} | +/- 0.12 | t-interval (SD=0.2, n=10)",
            f"RQD | In-Context (B) | {ic_delta:+.2f} | +/- {ic_half:.2f} | t-interval (n={n_ic_rqd})",
            "table2 rqd in_context",
        )
    )
    rs.append(
        (
            f"RQD | MemoGraph (C) | +{o_rqd['memograph']} | +/- 0.12 | t-interval (SD=0.2, n=10)",
            f"RQD | MemoGraph (C) | {mg_delta:+.2f} | +/- {mg_half:.2f} | t-interval (n={n_mg_rqd})",
            "table2 rqd memograph",
        )
    )

    o_g = old["graph"]
    n_g = new["graph"]
    rs.append(
        (
            f"suggested **{o_g['total_suggestions']}** wikilink",
            f"suggested **{n_g['total_suggestions']}** wikilink",
            "graph suggestions",
        )
    )
    rs.append(
        (
            f"of which **{o_g['accepted_links']}**",
            f"of which **{n_g['accepted_links']}**",
            "graph accepted",
        )
    )
    rs.append(
        (
            f"acceptance rate: **{o_g['acceptance_rate']}%**",
            f"acceptance rate: **{fmt_pct(n_g['acceptance_rate'])}%**",
            "graph acceptance rate",
        )
    )
    rs.append(
        (
            f"In **{o_g['enriched_queries']}** out of **{o_g['total_queries_with_matches']}** queries (**{o_g['enrichment_rate']}%**)",
            f"In **{n_g['enriched_queries']}** out of **{n_g['total_queries_with_matches']}** queries (**{fmt_pct(n_g['enrichment_rate'])}%**)",
            "graph enrichment",
        )
    )
    rs.append(
        (
            f"average node degree (number of connections per memory) was **{o_g['avg_node_degree']}**",
            f"average node degree (number of connections per memory) was **{n_g['avg_node_degree']}**",
            "graph avg degree",
        )
    )
    rs.append(
        (
            f"maximum degree of **{o_g['max_node_degree']}**",
            f"maximum degree of **{n_g['max_node_degree']}**",
            "graph max degree",
        )
    )
    rs.append(
        (
            f"contained **{o_g['isolated_nodes']}** isolated nodes",
            f"contained **{n_g['isolated_nodes']}** isolated nodes",
            "graph isolated",
        )
    )
    rs.append(
        (
            f"representing **{o_g['isolation_percentage']}%**",
            f"representing **{fmt_pct(n_g['isolation_percentage'])}%**",
            "graph isolation pct",
        )
    )
    rs.append(
        (
            f"hooks correctly in **{o_g['auto_save_compliance']}%**",
            f"create_memory tool calls fired correctly in **{fmt_pct(n_g['auto_save_compliance'])}%**",
            "graph auto-save",
        )
    )

    rs.append(("Claude Sonnet 3.5", "Claude Sonnet 4.6", "model name 3.5->4.6 (1)"))
    rs.append(("Claude Sonnet 3.5", "Claude Sonnet 4.6", "model name 3.5->4.6 (2)"))

    if calibration:
        crs_cal = (calibration.get("per_dimension") or {}).get("crs") or {}
        kappa = crs_cal.get("kappa")
        n_pairs = crs_cal.get("n")
        if kappa is not None:
            rs.append(
                (
                    "[kappa = TBD from real experiment]",
                    f"Cohen's kappa (CRS, author vs. LLM judge, n={n_pairs}) = {kappa:.3f} (quadratic-weighted)",
                    "kappa",
                )
            )

    return rs


SYNTH_BLOCK = "> **Warning - Data Disclosure:** The numerical results presented in this section are **synthetic/simulated** values generated for structural demonstration purposes (see `scripts/generate_synthetic_experimental_data.py`). They were produced using pre-specified realistic ranges (e.g., MRA: MemoGraph 80-95%, In-Context 60-75%, Baseline 10-20%) and a fixed random seed (42), not collected from real experiments. **These results must be replaced with real experimental data before any academic submission.** The experimental protocol for collecting real data is documented in `paper/09_experimental_protocol.md`."

REAL_BLOCK = (
    "> **Methodology Disclosure:** The numerical results presented here come from an "
    "automated evaluation pipeline (`scripts/run_real_experiments.py` and "
    "`scripts/score_experiments.py`) rather than the manual chat-based protocol described "
    "in `paper/09_experimental_protocol.md` (an addendum in that document records this "
    "deviation). All three conditions were driven through the Anthropic Messages API with "
    "Claude Sonnet 4.6 as the response model. CRS and the per-dimension RQD scores were "
    "produced by Claude Opus 4.7 acting as a blinded judge against the rubric in "
    "`paper/experimental_materials/02_evaluation_rubric.md`; this judge was calibrated "
    "against author scores on a stratified 30-response sample (Cohen's kappa reported in "
    "Section 4.3.1). Condition B used a TF-IDF curator over prior-session exchanges in "
    "place of a human in-context curator. Condition C invoked a `MemoryKernel` directly via "
    "tool-use loops rather than the Claude Desktop MCP transport. These deviations and "
    "their threats to validity are documented in Section 5."
)


def replace_synthetic_disclaimer(text: str) -> tuple[str, int]:
    if SYNTH_BLOCK in text:
        return text.replace(SYNTH_BLOCK, REAL_BLOCK), 1
    sys.stderr.write(
        "WARNING: synthetic disclaimer block not found verbatim; leaving as is\n"
    )
    return text, 0


SYNTH_S5_4 = """### 5.4 Synthetic Data Limitations

Because the results in this section are currently synthetic (see Data Disclosure above), all threats described above are compounded: the numbers do not reflect actual experimental execution. The confidence intervals are computed from assumed sample sizes and assumed standard deviations, not from observed data. The ordering of conditions (MemoGraph > In-Context > Baseline) is guaranteed by construction in the data generation script, not by empirical measurement. **No scientific conclusions should be drawn from these numbers until real experimental data has been collected following `paper/09_experimental_protocol.md`.**"""

REAL_S5_4 = """### 5.4 Automated Pipeline, LLM-as-Judge, and Retriever-Wrapper Limitations

The evaluation reported here was produced by an automated pipeline (`scripts/run_real_experiments.py`) rather than the manual chat-based protocol originally specified in `paper/09_experimental_protocol.md`. Four deviations follow from this and warrant explicit caveats. First, CRS and RQD scores come from a single LLM judge (Claude Opus 4.7) calibrated against author scores on a 30-response sample; LLM-as-judge methods are known to exhibit length bias, position bias, and self-consistency drift. We mitigate same-model bias by using Opus 4.7 for judging while Sonnet 4.6 generates responses, and we report Cohen's kappa against author scores in Section 4.3.1, but the judge is not a substitute for a panel of independent human evaluators. Second, Condition B uses a TF-IDF curator to select up to four prior-session exchanges per query; this is a stronger and more uniform retrieval than a tired human curator would produce, which conservatively narrows the gap between Conditions B and C and may understate MemoGraph's relative advantage in deployments where the in-context alternative is fully manual. Third, Condition C invokes the `MemoryKernel` directly via tool-use loops in the Anthropic API rather than through the Claude Desktop MCP transport; the artifact under test is the same Python kernel, but real-world MCP latency, transport-level error handling, and Claude Desktop's own tool-use behaviour are not exercised. Fourth — and most importantly for interpreting MemoGraph's MRA scores — the v0.1.0 kernel's no-embedding fallback in `HybridRetriever.retrieve` (memograph/core/retriever.py lines 47-55) ranks candidates by `(salience, access_count)` rather than by query relevance, so a literal call to `kernel.search()` without a configured embedding adapter is salience-only. The harness wraps the `search_memories` tool with a TF-IDF scorer over the in-memory graph nodes' titles and content (`scripts/condition_runners.py::_tfidf_rank_kernel_nodes`), which is what a working keyword/BM25 path is intended to provide. The numbers reported here therefore reflect MemoGraph's design intent rather than the v0.1.0 release as-shipped; closing this gap by implementing in-kernel BM25 ranking is the highest-priority follow-up before any subsequent submission. A future replication using the manual protocol with independent human evaluators, the MCP transport, and a kernel that ranks keyword strategies natively remains the strongest path to externally valid claims and is listed as future work."""


def replace_section_5_4(text: str) -> tuple[str, int]:
    if SYNTH_S5_4 in text:
        return text.replace(SYNTH_S5_4, REAL_S5_4), 1
    sys.stderr.write(
        "WARNING: synthetic Section 5.4 block not found verbatim; leaving as is\n"
    )
    return text, 0


def find_remaining_placeholders(text: str) -> list[str]:
    return sorted(set(re.findall(r"\[[A-Z][A-Z0-9/+\.\s]*\]", text)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--old", type=Path, default=None, help="path to OLD (synthetic) results JSON"
    )
    args = ap.parse_args()

    if not NEW_RESULTS.exists():
        sys.stderr.write(
            f"ERROR: {NEW_RESULTS} missing. Run scripts/score_experiments.py first.\n"
        )
        return 2

    new = json.loads(NEW_RESULTS.read_text(encoding="utf-8"))

    if args.old and args.old.exists():
        old = json.loads(args.old.read_text(encoding="utf-8"))
    elif SYNTHETIC_BACKUP.exists():
        old = json.loads(SYNTHETIC_BACKUP.read_text(encoding="utf-8"))
    else:
        old = SYNTHETIC_FALLBACK
        print(
            "Using built-in synthetic fallback as 'old' values (no _synthetic_results.json found)."
        )

    judge = load_judge_per_condition()
    if not judge:
        print(
            "WARNING: no judge_scores.jsonl found; CRS/RQD intervals will fall back to point values."
        )

    cal = (
        json.loads(CALIBRATION.read_text(encoding="utf-8"))
        if CALIBRATION.exists()
        else None
    )

    text = EVAL_MD.read_text(encoding="utf-8")

    text, n_warn = replace_synthetic_disclaimer(text)
    text, n_s54 = replace_section_5_4(text)

    total = n_warn + n_s54
    for old_s, new_s, label in build_replacements(old, new, judge, cal):
        text, n = safe_replace(text, old_s, new_s, required=True, label=label)
        total += n

    remaining = find_remaining_placeholders(text)
    if args.dry_run:
        print(f"Would apply {total} replacements.")
        if remaining:
            print(f"Remaining bracketed placeholders: {remaining}")
        return 0

    EVAL_MD.write_text(text, encoding="utf-8")
    print(f"Applied {total} replacements to {EVAL_MD}.")
    if remaining:
        print(
            f"NOTE: {len(remaining)} bracketed placeholders still present: {remaining}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
