#!/usr/bin/env python3
"""Helper: writes insert_experimental_data.py and validate_experimental_data.py."""

INSERT_SCRIPT = '''\
#!/usr/bin/env python3
"""
Insert synthetic experimental data into paper/05_evaluation.md.
Reads paper/experimental_results.json and replaces all placeholders.
Uses only Python standard library (json, re).
"""

import json
import re
from pathlib import Path


def load_results(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def replace_placeholders(content, results):
    count = 0

    baseline_csc  = results["csc"]["baseline"]
    ic_csc        = results["csc"]["in_context"]
    mg_csc        = results["csc"]["memograph"]
    baseline_pct  = round((baseline_csc  / 15) * 100, 1)
    ic_pct        = round((ic_csc        / 15) * 100, 1)
    mg_pct        = round((mg_csc        / 15) * 100, 1)

    mra_mg  = str(results["mra"]["memograph"])
    mra_ic  = str(results["mra"]["in_context"])
    mra_bl  = str(results["mra"]["baseline"])
    crs_mg  = str(results["crs"]["memograph"])
    crs_ic  = str(results["crs"]["in_context"])
    crs_bl  = str(results["crs"]["baseline"])
    rqd_mg  = str(results["rqd"]["memograph"])
    rqd_ic  = str(results["rqd"]["in_context"])
    g_ts    = str(results["graph"]["total_suggestions"])
    g_al    = str(results["graph"]["accepted_links"])
    g_ar    = str(results["graph"]["acceptance_rate"])
    g_eq    = str(results["graph"]["enriched_queries"])
    g_tqm   = str(results["graph"]["total_queries_with_matches"])
    g_er    = str(results["graph"]["enrichment_rate"])
    g_and   = str(results["graph"]["avg_node_degree"])
    g_mnd   = str(results["graph"]["max_node_degree"])
    g_iso   = str(results["graph"]["isolated_nodes"])
    g_isopc = str(results["graph"]["isolation_percentage"])
    g_asc   = str(results["graph"]["auto_save_compliance"])

    pairs = [
        # --- MRA prose ---
        (
            r"MemoGraph \\(Condition C\\) achieved an MRA of \\*\\*\\[X\\]%\\*\\*",
            "MemoGraph (Condition C) achieved an MRA of **" + mra_mg + "%**",
        ),
        (
            r"compared to \\*\\*\\[Y\\]%\\*\\* for in-context memory \\(Condition B\\)",
            "compared to **" + mra_ic + "%** for in-context memory (Condition B)",
        ),
        (
            r"and \\*\\*\\[Z\\]%\\*\\* for the baseline \\(Condition A\\)",
            "and **" + mra_bl + "%** for the baseline (Condition A)",
        ),
        # --- CRS prose ---
        (
            r"MemoGraph achieved an average CRS of \\*\\*\\[X\\.XX\\]\\*\\* out of 5",
            "MemoGraph achieved an average CRS of **" + crs_mg + "** out of 5",
        ),
        (
            r"compared to \\*\\*\\[Y\\.YY\\]\\*\\* for in-context memory",
            "compared to **" + crs_ic + "** for in-context memory",
        ),
        (
            r"and \\*\\*\\[Z\\.ZZ\\]\\*\\* for the baseline",
            "and **" + crs_bl + "** for the baseline",
        ),
        # --- CSC prose ---
        (
            r"MemoGraph correctly recalled \\*\\*\\[X\\]\\*\\* out of 15 long-term facts \\(CSC = \\*\\*\\[X/15 \xd7 100\\]%\\*\\*\\)",
            "MemoGraph correctly recalled **" + str(mg_csc) + "** out of 15 long-term facts (CSC = **" + str(mg_pct) + "%**)",
        ),
        (
            r"compared to \\*\\*\\[Y\\]\\*\\* for in-context memory \\(CSC = \\*\\*\\[Y/15 \xd7 100\\]%\\*\\*\\)",
            "compared to **" + str(ic_csc) + "** for in-context memory (CSC = **" + str(ic_pct) + "%**)",
        ),
        (
            r"and \\*\\*\\[Z\\]\\*\\* for the baseline \\(CSC = \\*\\*\\[Z/15 \xd7 100\\]%\\*\\*\\)",
            "and **" + str(baseline_csc) + "** for the baseline (CSC = **" + str(baseline_pct) + "%**)",
        ),
        # --- RQD prose ---
        (
            r"MemoGraph improved response quality by \\*\\*\\[\\+X\\.XX\\]\\*\\* points",
            "MemoGraph improved response quality by **+" + rqd_mg + "** points",
        ),
        (
            r"while in-context memory improved by \\*\\*\\[\\+Y\\.YY\\]\\*\\* points",
            "while in-context memory improved by **+" + rqd_ic + "** points",
        ),
        # --- Table 1 rows ---
        (
            r"\\| Memory Retrieval Accuracy \\(%\\) \\| \\[Z\\] \\| \\[Y\\] \\| \\[X\\] \\|",
            "| Memory Retrieval Accuracy (%) | " + mra_bl + " | " + mra_ic + " | " + mra_mg + " |",
        ),
        (
            r"\\| Context Relevance Score \\(1-5\\) \\| \\[Z\\.ZZ\\] \\| \\[Y\\.YY\\] \\| \\[X\\.XX\\] \\|",
            "| Context Relevance Score (1-5) | " + crs_bl + " | " + crs_ic + " | " + crs_mg + " |",
        ),
        (
            r"\\| Cross-Session Consistency \\(%\\) \\| \\[Z/15 \xd7 100\\] \\| \\[Y/15 \xd7 100\\] \\| \\[X/15 \xd7 100\\] \\|",
            "| Cross-Session Consistency (%) | " + str(baseline_pct) + " | " + str(ic_pct) + " | " + str(mg_pct) + " |",
        ),
    ]
'''
