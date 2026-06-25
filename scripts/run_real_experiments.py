#!/usr/bin/env python3
"""Drive all three experimental conditions end-to-end against the Anthropic API.

Usage:
    python scripts/run_real_experiments.py --smoke
    python scripts/run_real_experiments.py --full
    python scripts/run_real_experiments.py --sessions 1,2,3 --conditions memograph

Logs land under paper/experimental_runs/{condition}/session_{N}.jsonl.
The Condition C vault lives at paper/experimental_runs/vaults/condition_c/.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

import anthropic

from _paper_eval_helpers import (
    QUERIES_JSON,
    RUNS_DIR,
    QueriesDoc,
    require_anthropic_key,
)
from condition_runners import (
    CallLog,
    Exchange,
    run_baseline_session,
    run_in_context_session,
    run_memograph_session,
    write_session_log,
)

CONDITIONS = ("baseline", "in_context", "memograph")


def _logs_to_exchanges(
    logs: list[CallLog], queries_by_idx: dict[int, str]
) -> list[Exchange]:
    out = []
    for cl in logs:
        if cl.response_text:
            out.append(
                Exchange(
                    session_id=cl.session_id,
                    query_idx=cl.query_idx,
                    query_text=queries_by_idx.get(cl.query_idx, ""),
                    response_text=cl.response_text,
                )
            )
    return out


def run_condition(
    name: str,
    client,
    sessions,
    queries_by_idx,
    out_root: Path,
    *,
    fresh_vault: bool = False,
):
    cond_dir = out_root / name
    cond_dir.mkdir(parents=True, exist_ok=True)

    history: list[Exchange] = []
    kernel = None
    if name == "memograph":
        from memograph.core.kernel import MemoryKernel

        vault_root = out_root / "vaults" / "condition_c"
        if fresh_vault and vault_root.exists():
            shutil.rmtree(vault_root)
        vault_root.mkdir(parents=True, exist_ok=True)
        kernel = MemoryKernel(vault_path=str(vault_root))

    grand_total = 0
    grand_errors = 0
    for s in sessions:
        t0 = time.time()
        if name == "baseline":
            logs = run_baseline_session(client, s.queries)
        elif name == "in_context":
            logs = run_in_context_session(client, s.queries, history)
        elif name == "memograph":
            logs = run_memograph_session(client, s.queries, kernel)
        else:
            raise ValueError(name)

        write_session_log(cond_dir / f"session_{s.id:02d}.jsonl", logs)
        history.extend(_logs_to_exchanges(logs, queries_by_idx))

        n_err = sum(1 for cl in logs if cl.error)
        elapsed = time.time() - t0
        print(
            f"  [{name}] session {s.id:02d}: {len(logs)} queries, {n_err} errors, "
            f"{elapsed:.1f}s"
        )
        grand_total += len(logs)
        grand_errors += n_err

    print(f"  [{name}] TOTAL: {grand_total} queries, {grand_errors} errors")
    return grand_total, grand_errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="run only session 1")
    ap.add_argument("--full", action="store_true", help="run all 10 sessions")
    ap.add_argument(
        "--sessions",
        type=str,
        default=None,
        help="comma-separated session ids, e.g. 1,2,3",
    )
    ap.add_argument(
        "--conditions",
        type=str,
        default=",".join(CONDITIONS),
        help=f"comma-separated subset of: {','.join(CONDITIONS)}",
    )
    ap.add_argument(
        "--fresh-vault",
        action="store_true",
        help="wipe Condition C vault before running",
    )
    args = ap.parse_args()

    if not args.smoke and not args.full and args.sessions is None:
        ap.error("pick one of --smoke, --full, --sessions")

    require_anthropic_key()

    if not QUERIES_JSON.exists():
        sys.stderr.write(
            f"ERROR: {QUERIES_JSON} missing. Run parse_experimental_materials.py first.\n"
        )
        return 2

    doc = QueriesDoc.from_json_path(QUERIES_JSON)

    if args.smoke:
        session_ids = {1}
    elif args.full:
        session_ids = {s.id for s in doc.sessions}
    else:
        session_ids = {int(x) for x in args.sessions.split(",")}
    sessions = [s for s in doc.sessions if s.id in session_ids]
    sessions.sort(key=lambda s: s.id)

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    bad = [c for c in conditions if c not in CONDITIONS]
    if bad:
        ap.error(f"unknown condition(s): {bad}; valid: {CONDITIONS}")

    queries_by_idx = {q.idx: q.text for s in doc.sessions for q in s.queries}

    print(
        f"Running conditions={conditions} sessions={sorted(session_ids)} "
        f"({sum(len(s.queries) for s in sessions)} queries each)"
    )

    client = anthropic.Anthropic()

    overall = {}
    for cond in conditions:
        print(f"\n=== {cond} ===")
        overall[cond] = run_condition(
            cond,
            client,
            sessions,
            queries_by_idx,
            RUNS_DIR,
            fresh_vault=(args.fresh_vault and cond == "memograph"),
        )

    print("\nDone.")
    for cond, (n, errs) in overall.items():
        print(f"  {cond}: {n} queries, {errs} errors")
    return 0 if all(errs == 0 for _, errs in overall.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
