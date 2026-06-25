#!/usr/bin/env python3
"""Parse paper/experimental_materials/{01_query_list.md, 03_ground_truth.md}
into a structured paper/experimental_runs/queries.json.

Usage:
    python scripts/parse_experimental_materials.py            # write queries.json
    python scripts/parse_experimental_materials.py --validate # also assert invariants
"""

from __future__ import annotations

import argparse
import re
import sys

from _paper_eval_helpers import (
    MATERIALS_DIR,
    QUERIES_JSON,
    QueriesDoc,
    Query,
    Session,
    write_json,
)

QUERY_LIST_MD = MATERIALS_DIR / "01_query_list.md"
GROUND_TRUTH_MD = MATERIALS_DIR / "03_ground_truth.md"

# In query_list.md:
#   "## Session N: <title> (...)"
#   '8. [RETRIEVAL: YES - Session 1] "I'm setting up..."'
#   "**Expected Memories Created**:" then "- ..."
#
# In ground_truth.md:
#   "### Query N"
#   "**Query**: \"...\""
#   "**Retrieval Required**: YES (...)"
#   "**Ground Truth**: User chose Python; User uses VS Code"   (or "N/A" or multi-line bullets)
#   "**Memory Created**: User uses pytest"
#   "**CSC Fact**: #3 (IDE Choice), #1 (Language Preference)"


SESSION_HEAD_RE = re.compile(r"^##\s+Session\s+(\d+)\s*:\s*(.+?)(?:\s*\(.*\))?\s*$")
QUERY_LINE_RE = re.compile(
    r'^(?P<idx>\d+)\.\s+\[RETRIEVAL:\s*(?P<flag>YES|NO)(?:\s*-\s*(?P<src>[^\]]+))?\]\s+"(?P<text>.+)"\s*$'
)
GT_QUERY_HEAD_RE = re.compile(r"^###\s+Query\s+(\d+)\s*$")
SESSION_RANGE_RE = re.compile(r"Session\s+(\d+)(?:\s*[-–]\s*(\d+))?")


def _parse_source_sessions(src: str | None) -> list[int]:
    if not src:
        return []
    sessions: set[int] = set()
    if "all" in src.lower():
        return list(range(1, 6))
    for m in SESSION_RANGE_RE.finditer(src):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        sessions.update(range(a, b + 1))
    parts = re.findall(r"\b(\d+)\b", src)
    for p in parts:
        sessions.add(int(p))
    return sorted(sessions)


def parse_query_list() -> list[Session]:
    text = QUERY_LIST_MD.read_text(encoding="utf-8")
    sessions: list[Session] = []
    cur_session: Session | None = None
    cur_session_queries: list[Query] = []

    for line in text.splitlines():
        m = SESSION_HEAD_RE.match(line)
        if m:
            if cur_session is not None:
                cur_session.queries = cur_session_queries
                sessions.append(cur_session)
            cur_session = Session(
                id=int(m.group(1)), title=m.group(2).strip(), queries=[]
            )
            cur_session_queries = []
            continue

        if cur_session is None:
            continue

        qm = QUERY_LINE_RE.match(line)
        if qm:
            idx = int(qm.group("idx"))
            retrieval = qm.group("flag") == "YES"
            srcs = _parse_source_sessions(qm.group("src"))
            cur_session_queries.append(
                Query(
                    idx=idx,
                    session_id=cur_session.id,
                    session_idx=len(cur_session_queries) + 1,
                    text=qm.group("text"),
                    retrieval_required=retrieval,
                    retrieval_source_sessions=srcs,
                )
            )

    if cur_session is not None:
        cur_session.queries = cur_session_queries
        sessions.append(cur_session)
    return sessions


GT_GROUND_TRUTH_RE = re.compile(r"^\*\*Ground Truth\*\*:\s*(.*)$")
GT_MEMORY_RE = re.compile(r"^\*\*Memory Created\*\*:\s*(.*)$")
GT_CSC_RE = re.compile(r"^\*\*CSC Facts?\*\*:\s*(.*)$")


def _split_ground_truth_titles(value: str) -> list[str]:
    value = value.strip()
    if not value or value.upper() == "N/A":
        return []
    parts = [p.strip(" .") for p in re.split(r";|\n", value)]
    out = []
    for p in parts:
        p = p.strip("-• \t")
        if p and p.upper() != "N/A" and not p.startswith("**"):
            # Strip leading "Language: " style prefixes from the bulleted GT lines.
            if ":" in p and len(p.split(":", 1)[1].strip()) > 0:
                # Keep both halves; downstream MRA matcher uses substring search.
                pass
            out.append(p)
    return out


def parse_ground_truth() -> dict[int, dict]:
    """Returns: {query_idx: {"ground_truth_titles": [...], "memory_to_create": str|None, "csc_facts": [int, ...]}}"""
    text = GROUND_TRUTH_MD.read_text(encoding="utf-8")
    lines = text.splitlines()
    result: dict[int, dict] = {}

    cur_idx: int | None = None
    cur_gt_buf: list[str] = []
    cur_mem: str | None = None
    cur_csc: list[int] = []
    in_gt_multiline = False

    def flush() -> None:
        if cur_idx is None:
            return
        gt_text = "\n".join(cur_gt_buf).strip()
        result[cur_idx] = {
            "ground_truth_titles": _split_ground_truth_titles(gt_text),
            "memory_to_create": cur_mem,
            "csc_facts": list(cur_csc),
        }

    for line in lines:
        hm = GT_QUERY_HEAD_RE.match(line.strip())
        if hm:
            flush()
            cur_idx = int(hm.group(1))
            cur_gt_buf = []
            cur_mem = None
            cur_csc = []
            in_gt_multiline = False
            continue

        gm = GT_GROUND_TRUTH_RE.match(line)
        if gm:
            value = gm.group(1).strip()
            cur_gt_buf = [value]
            in_gt_multiline = True
            continue

        if in_gt_multiline:
            stripped = line.strip()
            # Bullet sub-lines of multi-line Ground Truth (e.g. "- Language: Python ...").
            # Require the space after the marker so that bold-prefixed fields like
            # "**Memory Created**:" or "**CSC Fact**:" don't get misread as bullets.
            if stripped.startswith("- ") or stripped.startswith("* "):
                cur_gt_buf.append(stripped[2:])
                continue
            # Any new bold field, header, or blank line ends the multi-line GT capture.
            if (
                stripped.startswith("**")
                or stripped.startswith("###")
                or stripped.startswith("---")
                or stripped == ""
            ):
                in_gt_multiline = False
                # fall through so the line can be matched against Memory / CSC regexes
            else:
                if stripped:
                    cur_gt_buf.append(stripped)
                    continue

        mm = GT_MEMORY_RE.match(line)
        if mm:
            cur_mem = mm.group(1).strip()
            continue

        cm = GT_CSC_RE.match(line)
        if cm:
            for n in re.findall(r"#(\d+)", cm.group(1)):
                cur_csc.append(int(n))
            continue

    flush()
    return result


def build_doc() -> QueriesDoc:
    sessions = parse_query_list()
    gt = parse_ground_truth()

    for s in sessions:
        for q in s.queries:
            entry = gt.get(q.idx)
            if entry is None:
                continue
            q.ground_truth_titles = entry["ground_truth_titles"]
            q.memory_to_create = entry["memory_to_create"]
            q.csc_facts = entry["csc_facts"]

    return QueriesDoc(sessions=sessions)


def validate(doc: QueriesDoc) -> list[str]:
    problems: list[str] = []
    queries = doc.all_queries()

    if len(queries) != 70:
        problems.append(f"expected 70 queries, got {len(queries)}")
    if len(doc.sessions) != 10:
        problems.append(f"expected 10 sessions, got {len(doc.sessions)}")

    retrieval_count = sum(1 for q in queries if q.retrieval_required)
    if retrieval_count < 40:
        problems.append(f"expected >=40 retrieval queries, got {retrieval_count}")

    seen_idxs = sorted(q.idx for q in queries)
    if seen_idxs != list(range(1, 71)):
        problems.append(
            f"non-contiguous query idxs; first gap near {next((i + 1 for i, v in enumerate(seen_idxs) if v != i + 1), 'n/a')}"
        )

    csc_facts_seen = set()
    for q in queries:
        csc_facts_seen.update(q.csc_facts)
    # Per the protocol, 15 long-term facts are tracked. The materials annotate them
    # with #1..#15 across queries. We just sanity-check the upper bound.
    if csc_facts_seen and (max(csc_facts_seen) > 15 or min(csc_facts_seen) < 1):
        problems.append(f"CSC fact ids out of [1,15]: {sorted(csc_facts_seen)}")

    # Session 1-5 should have memory_to_create on most queries; sessions 6-10 mostly None.
    for s in doc.sessions:
        if s.id <= 5:
            mems = sum(1 for q in s.queries if q.memory_to_create)
            if mems == 0:
                problems.append(f"session {s.id}: zero memories_to_create parsed")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    doc = build_doc()
    write_json(QUERIES_JSON, doc.to_json())

    queries = doc.all_queries()
    print(
        f"Wrote {QUERIES_JSON} ({len(queries)} queries across {len(doc.sessions)} sessions)"
    )
    print(f"  retrieval=YES: {sum(1 for q in queries if q.retrieval_required)}")
    print(f"  retrieval=NO:  {sum(1 for q in queries if not q.retrieval_required)}")
    csc_facts_seen = set()
    for q in queries:
        csc_facts_seen.update(q.csc_facts)
    print(f"  distinct CSC facts annotated: {sorted(csc_facts_seen)}")

    if args.validate:
        problems = validate(doc)
        if problems:
            print("VALIDATION PROBLEMS:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("VALIDATION: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
