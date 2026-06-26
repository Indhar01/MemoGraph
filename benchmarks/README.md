# MemoGraph benchmarks

This directory is the **public reproduction harness** for MemoGraph's
evaluation. The full paper-quality experimental pipeline lives under
[`paper/experimental_runs/`](../paper/experimental_runs/); this folder
is the lightweight, public-facing entrypoint into it.

If you want to:

- **See the numbers** → [BENCHMARKS.md at the repo root](../BENCHMARKS.md)
- **Reproduce a single run** → start with [`paper/experimental_runs/`](../paper/experimental_runs/) and follow [`paper/09_experimental_protocol.md`](../paper/09_experimental_protocol.md)
- **Compare MemoGraph to another memory system** → read § "Adding a new system" below

## Why this isn't a fresh harness

A common mistake at this point in a project is to build a parallel
"public benchmark" alongside an existing internal one. The two then
drift, results stop matching, and external observers (reviewers,
adopters) don't know which to trust.

MemoGraph's evaluation pipeline already exists in `paper/`. This folder
just **surfaces** it — the same queries, vaults, judge prompts, and
scoring — under a path external users expect (`/benchmarks`).

If you want to add a new dataset or evaluator, extend the pipeline in
`paper/experimental_runs/` and reference it here. **Do not fork.**

## Current results (v6, 2026-06-21)

| Metric | Baseline (A) | In-context (B) | MemoGraph (C) |
|---|---|---|---|
| **MRA** (lenient, %) | 40.9 | 81.8 | **81.8** |
| **MRA strict** (%) | 0.0 | 73.1 | **73.1** |
| **CRS** (1-5) | 2.53 | 2.66 | **3.04** |
| **CSC** (facts recalled / 15) | 13 | 14 | **14** |
| **RQD** (Δ vs baseline) | — | +0.35 | **+0.39** |

- Generator: `claude-sonnet-4-6`
- Judge: `claude-opus-4-7` (blinded, calibrated against a second LLM evaluator)
- 70 queries across 10 sessions
- Knowledge graph: 16 memories, 33 wikilinks, avg node degree 4.12, 0 isolated nodes
- Graph expansion contributed context to 65/66 queries with a search hit (98.5%)

> **⚠️ Data caveat.** The v6 numbers above were produced on a
> **synthetic** scenario set — 10 multi-session software-development
> conversations authored by a generator LLM. Real-user data collection
> is in progress; until that lands, treat these as **upper bounds for
> the synthetic distribution**, not generalisation claims. Same
> disclosure appears verbatim in the paper at
> [`paper/05_evaluation.md`](../paper/05_evaluation.md).

## Adding a new system to compare against

The protocol in [`paper/09_experimental_protocol.md`](../paper/09_experimental_protocol.md)
defines three conditions:

- **A**: Sonnet 4.6 with no memory (lower bound)
- **B**: Sonnet 4.6 with TF-IDF in-context curation (strong baseline)
- **C**: Sonnet 4.6 + MemoGraph MCP server

To add a fourth condition (e.g. **D**: Sonnet 4.6 + mem0), you need:

1. **An MCP server** (or equivalent transport) so the same generator
   harness can call it. mem0 has an MCP wrapper; others may need one.
2. **Per-session state isolation** matching the existing rig — each of
   the 10 sessions starts with the *previous* session's persisted state.
3. **Run all 70 queries** through the new condition. Save the
   transcripts as `paper/experimental_runs/<system>/session_*.jsonl`.
4. **Score with the same judge** (`claude-opus-4-7`, prompts in
   `paper/experimental_runs/`). Don't change the judge prompt mid-run —
   re-score the existing conditions if you do.
5. **Open a PR** with the new transcripts + `_results_v<N+1>.json` and
   a one-paragraph methods note. The maintainers will re-run the judge
   on a sample to spot-check before merge.

## Why not LoCoMo / LongBench / etc.?

Three reasons MemoGraph doesn't yet report on the public memory
benchmarks you might expect:

1. **LoCoMo** is designed for evaluating *conversation summarisation*
   over long dialogues; MemoGraph is a *cross-session* memory system,
   not an intra-conversation one. The signal would be weak.
2. **LongBench** measures retrieval against a single long document, not
   accumulated state across many sessions. Wrong primitive.
3. **MemEval, MemGPT's own benchmark** — closed-source eval set; not
   reproducible.

We chose to build a small, focused 10-session 70-query rig that
specifically isolates *cross-session* recall. The cost is that the
absolute numbers can't be compared directly to LoCoMo papers. The
benefit is that the contrast between baseline / in-context / MemoGraph
*within* the same rig is internally valid.

Adding a LoCoMo run is welcome — see "Adding a new system" above.

## File map

```
benchmarks/
  README.md            ← this file
../BENCHMARKS.md       ← public results summary (referenced from main README)

paper/
  09_experimental_protocol.md     ← the protocol
  experimental_runs/
    queries.json                  ← 70 queries × 10 sessions
    calibration.json              ← judge calibration anchors
    baseline/session_*.jsonl      ← condition A transcripts
    in_context/session_*.jsonl    ← condition B transcripts
    memograph/session_*.jsonl     ← condition C transcripts
    _judge_scores_v6.jsonl        ← raw judge scores
    _results_v6.json              ← aggregated metrics (the numbers above)
    full_run_v6.log               ← run log
    scoring_v6.log                ← scoring log
    vaults/condition_c/*.md       ← MemoGraph's final vault state
```
