# MemoGraph benchmarks

Headline numbers, with caveats, for people who want to know if this
thing works before installing it.

> **⚠️ Data caveat.** The numbers below are from a **synthetic**
> 10-session, 70-query software-development scenario set. Real-user
> data collection is in progress. Treat these as upper bounds for the
> synthetic distribution, not generalisation claims.
>
> Full disclosure of methodology and threats to validity lives in
> [`paper/05_evaluation.md`](paper/05_evaluation.md) §5.

## Setup

- **Generator**: Claude Sonnet 4.6 (`claude-sonnet-4-6`)
- **Judge**: Claude Opus 4.7 (`claude-opus-4-7`), blinded, calibrated
  against a second LLM evaluator
- **Sessions**: 10 multi-session conversations
- **Queries**: 70 total across all sessions (18 leading, 52 non-leading)
- **Three conditions**:
  - **A** — generator with no memory (lower bound)
  - **B** — generator with TF-IDF in-context curation (strong baseline)
  - **C** — generator + MemoGraph MCP server

Results below are from the **v6** pipeline run on 2026-06-21.

## Headline results

| Metric | Baseline (A) | In-context (B) | MemoGraph (C) |
|---|---:|---:|---:|
| **Memory Retrieval Accuracy** (lenient, %) | 40.9 | 81.8 | **81.8** |
| **Memory Retrieval Accuracy** (strict, %)¹ | 0.0 | 73.1 | **73.1** |
| **Context Relevance Score** (1-5)² | 2.53 | 2.66 | **3.04** |
| **Cross-Session Consistency** (facts recalled / 15) | 13 | 14 | **14** |
| **Response Quality Delta** (Δ vs A) | — | +0.35 | **+0.39** |

¹ Excludes the 18 leading queries (those whose phrasing reveals the
expected answer). Strict MRA is the contamination-free signal.

² Judge rates the relevance of context the generator used to answer.
Scale: 1=irrelevant, 5=directly addresses the query.

## What this means

- On **finding the right memory**, MemoGraph **matches** the strong
  in-context curator (81.8% / 73.1%) — without requiring a human to
  pre-curate context for each query.
- On **using context well** (CRS), MemoGraph **outperforms** the
  in-context baseline by **+0.38** (3.04 vs 2.66).
- On **session-over-session consistency** (CSC), MemoGraph and the
  in-context curator both recall 14/15 facts. Baseline reaches 13/15
  because two facts are mentioned early enough to ride the model's
  default context.
- On **response quality delta**, MemoGraph improves the generator's
  answers by **+0.39** on a 1-5 scale, vs +0.35 for in-context.

## Knowledge graph quality

The MemoGraph condition produces a graph as a side effect of running
the protocol:

| Property | Value |
|---|---:|
| Total memories | 16 |
| Total wikilinks | 33 |
| Average node degree | 4.12 |
| Max node degree | 14 |
| Isolated nodes | 0 |
| Queries enriched by graph expansion | 65 / 66 (98.5%) |
| Link-suggestion acceptance rate | 100% |

The 100% link-acceptance rate is the autonomous LinkerAgent's
suggestions accepted by the heuristic gate — humans were not in the
loop. The number says the suggestion quality is high enough to merge
unsupervised, not that all 33 links are semantically perfect.

## Reproducing these numbers

1. `pip install -e ".[dev,all]"`
2. Set `ANTHROPIC_API_KEY`
3. Follow [`paper/09_experimental_protocol.md`](paper/09_experimental_protocol.md)
4. The pipeline regenerates `_results_v<N>.json`; compare to v6 above

If you fork the protocol, please version-stamp the result file
(`_results_v<N>.json`) and note the diff vs v6 in your PR.

## Comparing to other memory systems

MemoGraph hasn't been benchmarked against mem0, MemGPT, LangChain
Memory, Zep, or Letta in a shared rig yet. Adding a comparison is
welcome — see [`benchmarks/README.md`](benchmarks/README.md) for the
contribution recipe.

We deliberately don't report on LoCoMo / LongBench. Those benchmarks
measure **intra-conversation** memory; MemoGraph is a **cross-session**
system. Apples and oranges, and reviewers spot the mismatch fast.

## What changed between versions

| Version | Date | Change |
|---|---|---|
| v6 | 2026-06-21 | BM25 keyword retrieval + forced graph re-ingest before search |
| v5 | earlier | Salience-only ranking; graph occasionally stale at search time |

The v5→v6 delta is the bulk of MemoGraph's gain over the in-context
baseline on CRS. Both fixes are retained as part of MemoGraph
**v0.2.0+**.

## Threats to validity

In short:

- Synthetic scenario data (covered above)
- One generator, one judge — no model-family ablation yet
- Software-development domain only — generalisation to other domains
  not measured
- Judge LLM calibrated against another LLM, not against humans

Full discussion in [`paper/05_evaluation.md`](paper/05_evaluation.md)
§5 "Threats to Validity."

## Roadmap

- **Real user data**: 5 participants × 10 sessions, IRB-style consent,
  Q3 2026
- **Cross-domain run**: customer-support, project-management, personal
  assistant
- **Add mem0 and Letta** as conditions D and E
- **Human-in-the-loop scoring** on a 100-query subset to calibrate the
  LLM judge against a human gold standard
