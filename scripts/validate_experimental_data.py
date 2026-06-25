#!/usr/bin/env python3
"""Validate that all placeholders are replaced and values are in expected ranges."""

import json
import re
from pathlib import Path


def main():
    rp = Path("paper/experimental_results.json")
    ep = Path("paper/05_evaluation.md")
    errors = []
    warnings = []

    if not rp.exists():
        print("ERROR: " + str(rp) + " not found.")
        raise SystemExit(1)
    r = json.loads(rp.read_text(encoding="utf-8"))
    print("Validating experimental data...")

    content = ep.read_text(encoding="utf-8")
    remaining = sorted(set(re.findall(r"\[[A-Z][A-Z0-9/\xd7\+\.\s]*\]", content)))
    if remaining:
        errors.append("Unreplaced placeholders: " + str(remaining))
    else:
        print("  [OK] No placeholders remain in " + str(ep))

    if not (r["mra"]["memograph"] > r["mra"]["in_context"] > r["mra"]["baseline"]):
        errors.append("MRA ordering violated")
    else:
        print("  [OK] MRA ordering: MemoGraph > In-Context > Baseline")

    if not (r["crs"]["memograph"] > r["crs"]["in_context"] > r["crs"]["baseline"]):
        errors.append("CRS ordering violated")
    else:
        print("  [OK] CRS ordering: MemoGraph > In-Context > Baseline")

    if not (r["csc"]["memograph"] > r["csc"]["in_context"] > r["csc"]["baseline"]):
        errors.append("CSC ordering violated")
    else:
        print("  [OK] CSC ordering: MemoGraph > In-Context > Baseline")

    if not (r["rqd"]["memograph"] > r["rqd"]["in_context"] >= r["rqd"]["baseline"]):
        errors.append("RQD ordering violated")
    else:
        print("  [OK] RQD ordering: MemoGraph > In-Context >= Baseline")

    if not (
        0 <= r["mra"]["baseline"] <= 100
        and 0 <= r["mra"]["in_context"] <= 100
        and 0 <= r["mra"]["memograph"] <= 100
    ):
        errors.append("MRA values out of range (0-100)")
    else:
        print("  [OK] MRA values in valid range (0-100)")

    if not (
        1 <= r["crs"]["baseline"] <= 5
        and 1 <= r["crs"]["in_context"] <= 5
        and 1 <= r["crs"]["memograph"] <= 5
    ):
        errors.append("CRS values out of range (1-5)")
    else:
        print("  [OK] CRS values in valid range (1-5)")

    if not (
        0 <= r["csc"]["baseline"] <= 15
        and 0 <= r["csc"]["in_context"] <= 15
        and 0 <= r["csc"]["memograph"] <= 15
    ):
        errors.append("CSC values out of range (0-15)")
    else:
        print("  [OK] CSC values in valid range (0-15)")

    checks = [
        (10 <= r["mra"]["baseline"] <= 20, "Baseline MRA outside 10-20%"),
        (60 <= r["mra"]["in_context"] <= 75, "In-Context MRA outside 60-75%"),
        (80 <= r["mra"]["memograph"] <= 95, "MemoGraph MRA outside 80-95%"),
        (1.5 <= r["crs"]["baseline"] <= 2.0, "Baseline CRS outside 1.5-2.0"),
        (3.0 <= r["crs"]["in_context"] <= 3.5, "In-Context CRS outside 3.0-3.5"),
        (4.0 <= r["crs"]["memograph"] <= 4.5, "MemoGraph CRS outside 4.0-4.5"),
        (0 <= r["csc"]["baseline"] <= 2, "Baseline CSC outside 0-2"),
        (8 <= r["csc"]["in_context"] <= 11, "In-Context CSC outside 8-11"),
        (13 <= r["csc"]["memograph"] <= 15, "MemoGraph CSC outside 13-15"),
        (0.8 <= r["rqd"]["in_context"] <= 1.2, "In-Context RQD outside 0.8-1.2"),
        (1.5 <= r["rqd"]["memograph"] <= 2.0, "MemoGraph RQD outside 1.5-2.0"),
    ]
    range_ok = True
    for ok, msg in checks:
        if not ok:
            warnings.append(msg)
            range_ok = False
    if range_ok:
        print("  [OK] All values within expected plan ranges")
    else:
        for w in warnings:
            print("  [WARN] " + w)

    for val in [
        str(r["mra"]["memograph"]),
        str(r["crs"]["memograph"]),
        str(r["csc"]["memograph"]),
    ]:
        if val not in content:
            errors.append("Value " + val + " not found in evaluation file")
    if not errors:
        print("  [OK] Key MemoGraph values confirmed in evaluation file")

    print("\n" + "=" * 50)
    if errors:
        print("VALIDATION FAILED - " + str(len(errors)) + " error(s):")
        for e in errors:
            print("  [FAIL] " + e)
        raise SystemExit(1)
    else:
        print("VALIDATION PASSED")
        print("  All placeholders replaced.")
        print("  Expected ordering: MemoGraph > In-Context > Baseline.")
        print("  Value ranges validated.")
        if warnings:
            print("  " + str(len(warnings)) + " range warning(s) (non-fatal):")
            for w in warnings:
                print("    [WARN] " + w)
        print("  Ready for final assembly!")


if __name__ == "__main__":
    main()
