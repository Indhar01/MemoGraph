#!/usr/bin/env python3
"""Auto-fill paper/experimental_runs/calibration_template.json using a second LLM
(Claude Sonnet 4.6) as a blinded "second evaluator". Used in lieu of a human
calibrator when one is unavailable; the LLM-vs-LLM kappa is reported as
between-judge agreement, NOT human-anchored, and disclosed in 5_evaluation.md
Section 5.4.

Usage:
    python scripts/auto_score_calibration.py
"""

from __future__ import annotations

import json
import re
import sys
import time

from _paper_eval_helpers import RUNS_DIR, require_anthropic_key

TEMPLATE_PATH = RUNS_DIR / "calibration_template.json"
SECOND_EVALUATOR_MODEL = "claude-sonnet-4-6"  # different from JUDGE_MODEL (opus-4-7)

EVALUATOR_SYSTEM = """You are a careful evaluator assessing an AI assistant's response to a user query.
Score the response on these four dimensions, each on a 1-5 integer scale.

CRS (Context Relevance) — How relevant was any context the response drew on?
  5 = Highly relevant, directly enables a complete answer.
  4 = Mostly relevant, minor gaps.
  3 = Partially relevant, significant gaps.
  2 = Minimally relevant, mostly tangential.
  1 = Completely irrelevant or no context where context was clearly needed.

ACCURACY — Is the information correct?
  5 = Completely accurate. 4 = Mostly. 3 = Partially. 2 = Mostly inaccurate. 1 = Completely inaccurate.

COMPLETENESS — Does it fully answer the question?
  5 = Fully complete. 4 = Mostly. 3 = Partially. 2 = Mostly incomplete. 1 = Fails to address query.

PERSONALIZATION — Is it tailored to the user's specific context, decisions, and prior preferences?
  5 = Highly personalized; references specific user context.
  4 = Mostly personalized.
  3 = Some personalization, mostly generic.
  2 = Minimal personalization.
  1 = Completely generic.

Return a single JSON object on one line, no prose, no code fences:
{"crs": <1-5>, "accuracy": <1-5>, "completeness": <1-5>, "personalization": <1-5>}
"""


def score_one(client, query_text: str, response_text: str) -> dict | None:
    if not response_text.strip():
        return {"crs": 1, "accuracy": 1, "completeness": 1, "personalization": 1}
    user = (
        f"USER QUERY:\n{query_text}\n\n"
        f"AI RESPONSE:\n{response_text}\n\n"
        "Return the JSON object now."
    )
    try:
        resp = client.messages.create(
            model=SECOND_EVALUATOR_MODEL,
            max_tokens=128,
            system=EVALUATOR_SYSTEM,
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
    out = {}
    for k in ("crs", "accuracy", "completeness", "personalization"):
        v = scores.get(k, 1)
        out[k] = max(1, min(5, int(v))) if isinstance(v, (int, float)) else 1
    return out


def main() -> int:
    if not TEMPLATE_PATH.exists():
        sys.stderr.write(
            f"ERROR: {TEMPLATE_PATH} missing. Run calibrate_judge.py --prepare first.\n"
        )
        return 2

    require_anthropic_key()
    import anthropic

    items = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    client = anthropic.Anthropic()

    print(
        f"Auto-scoring {len(items)} calibration samples with {SECOND_EVALUATOR_MODEL}..."
    )
    t0 = time.time()
    for i, it in enumerate(items, 1):
        scores = score_one(client, it["query_text"], it["response_text"])
        if scores and "error" not in scores:
            it["human_scores"] = scores
        else:
            sys.stderr.write(f"  sample {it['sample_id']}: scoring error -- {scores}\n")
        if i % 5 == 0 or i == len(items):
            print(f"  scored {i}/{len(items)}  ({time.time() - t0:.1f}s elapsed)")

    TEMPLATE_PATH.write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote scores into {TEMPLATE_PATH}")
    print("Now run: python scripts/calibrate_judge.py --compute-kappa")
    return 0


if __name__ == "__main__":
    sys.exit(main())
