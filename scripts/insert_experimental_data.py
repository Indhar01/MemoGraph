#!/usr/bin/env python3
"""Insert synthetic experimental data into paper/05_evaluation.md."""

import json
import re
from pathlib import Path


def _sub(c, old, new):
    c2 = c.replace(old, new)
    return c2, (0 if c2 == c else 1)


def replace_placeholders(content, results):
    x = chr(215)
    subs = 0
    bl = results["csc"]["baseline"]
    ic = results["csc"]["in_context"]
    mg = results["csc"]["memograph"]
    bl_pct = round(bl / 15 * 100, 1)
    ic_pct = round(ic / 15 * 100, 1)
    mg_pct = round(mg / 15 * 100, 1)
    mra_mg = str(results["mra"]["memograph"])
    mra_ic = str(results["mra"]["in_context"])
    mra_bl = str(results["mra"]["baseline"])
    crs_mg = str(results["crs"]["memograph"])
    crs_ic = str(results["crs"]["in_context"])
    crs_bl = str(results["crs"]["baseline"])
    rqd_mg = str(results["rqd"]["memograph"])
    rqd_ic = str(results["rqd"]["in_context"])
    g = results["graph"]

    content, subs = _sub(content, "**[X]%**", "**" + mra_mg + "%**")
    content, n = _sub(content, "**[Y]%**", "**" + mra_ic + "%**")
    subs += n
    content, n = _sub(content, "**[Z]%**", "**" + mra_bl + "%**")
    subs += n
    content, n = _sub(content, "**[X.XX]**", "**" + crs_mg + "**")
    subs += n
    content, n = _sub(content, "**[Y.YY]**", "**" + crs_ic + "**")
    subs += n
    content, n = _sub(content, "**[Z.ZZ]**", "**" + crs_bl + "**")
    subs += n
    content, n = _sub(content, "**[X]** out of 15", "**" + str(mg) + "** out of 15")
    subs += n
    content, n = _sub(content, "[X/15 " + x + " 100]%", str(mg_pct) + "%")
    subs += n
    content, n = _sub(
        content, "**[Y]** for in-context", "**" + str(ic) + "** for in-context"
    )
    subs += n
    content, n = _sub(content, "[Y/15 " + x + " 100]%", str(ic_pct) + "%")
    subs += n
    content, n = _sub(
        content, "**[Z]** for the baseline", "**" + str(bl) + "** for the baseline"
    )
    subs += n
    content, n = _sub(content, "[Z/15 " + x + " 100]%", str(bl_pct) + "%")
    subs += n
    content, n = _sub(content, "**[+X.XX]**", "**+" + rqd_mg + "**")
    subs += n
    content, n = _sub(content, "**[+Y.YY]**", "**+" + rqd_ic + "**")
    subs += n

    content, n = _sub(
        content,
        "| [Z] | [Y] | [X] |",
        "| " + mra_bl + " | " + mra_ic + " | " + mra_mg + " |",
    )
    subs += n
    content, n = _sub(
        content,
        "| [Z.ZZ] | [Y.YY] | [X.XX] |",
        "| " + crs_bl + " | " + crs_ic + " | " + crs_mg + " |",
    )
    subs += n
    content, n = _sub(
        content,
        "| [Z/15 " + x + " 100] | [Y/15 " + x + " 100] | [X/15 " + x + " 100] |",
        "| " + str(bl_pct) + " | " + str(ic_pct) + " | " + str(mg_pct) + " |",
    )
    subs += n
    content, n = _sub(
        content, "| [+Y.YY] | [+X.XX] |", "| +" + rqd_ic + " | +" + rqd_mg + " |"
    )
    subs += n
    content, n = _sub(content, "**[N]**", "**" + str(g["total_suggestions"]) + "**")
    subs += n
    content, n = _sub(content, "**[M]**", "**" + str(g["accepted_links"]) + "**")
    subs += n
    content, n = _sub(content, "[M/N " + x + " 100]%", str(g["acceptance_rate"]) + "%")
    subs += n
    content, n = _sub(content, "**[P]**", "**" + str(g["enriched_queries"]) + "**")
    subs += n
    content, n = _sub(
        content, "**[Q]**", "**" + str(g["total_queries_with_matches"]) + "**"
    )
    subs += n
    content, n = _sub(content, "[P/Q " + x + " 100]%", str(g["enrichment_rate"]) + "%")
    subs += n
    content, n = _sub(content, "**[D.DD]**", "**" + str(g["avg_node_degree"]) + "**")
    subs += n
    content, n = _sub(content, "**[MAX]**", "**" + str(g["max_node_degree"]) + "**")
    subs += n
    content, n = _sub(content, "**[I]**", "**" + str(g["isolated_nodes"]) + "**")
    subs += n
    content, n = _sub(
        content, "[I/TOTAL " + x + " 100]%", str(g["isolation_percentage"]) + "%"
    )
    subs += n
    content, n = _sub(
        content, "**[R]%**", "**" + str(g["auto_save_compliance"]) + "%**"
    )
    subs += n
    return content, subs


def find_remaining(content):
    return sorted(set(re.findall(r"\[[A-Z][A-Z0-9/\xd7\+\.\s]*\]", content)))


def main():
    rp = Path("paper/experimental_results.json")
    ep = Path("paper/05_evaluation.md")
    if not rp.exists():
        print("ERROR: " + str(rp) + " not found. Run generate script first.")
        raise SystemExit(1)
    r = json.loads(rp.read_text(encoding="utf-8"))
    content = ep.read_text(encoding="utf-8")
    updated, count = replace_placeholders(content, r)
    ep.write_text(updated, encoding="utf-8")
    remaining = find_remaining(updated)
    print("Inserted experimental data into " + str(ep))
    print("  Replacements applied: " + str(count))
    if remaining:
        print(
            "  WARNING: "
            + str(len(remaining))
            + " placeholder(s) still present: "
            + str(remaining)
        )
    else:
        print("  All placeholders replaced.")
    print("\nSummary:")
    print(
        "  MRA:  Baseline="
        + str(r["mra"]["baseline"])
        + "%, In-Context="
        + str(r["mra"]["in_context"])
        + "%, MemoGraph="
        + str(r["mra"]["memograph"])
        + "%"
    )
    print(
        "  CRS:  Baseline="
        + str(r["crs"]["baseline"])
        + ", In-Context="
        + str(r["crs"]["in_context"])
        + ", MemoGraph="
        + str(r["crs"]["memograph"])
    )
    print(
        "  CSC:  Baseline="
        + str(r["csc"]["baseline"])
        + "/15, In-Context="
        + str(r["csc"]["in_context"])
        + "/15, MemoGraph="
        + str(r["csc"]["memograph"])
        + "/15"
    )
    print(
        "  RQD:  In-Context=+"
        + str(r["rqd"]["in_context"])
        + ", MemoGraph=+"
        + str(r["rqd"]["memograph"])
    )


if __name__ == "__main__":
    main()
