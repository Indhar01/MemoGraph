---
title: Python version policy
memory_type: fact
tags: [python, versioning, policy]
salience: 0.65
---

Project rule: support Python `N` and `N-1`, where `N` is the latest stable Python released more than 6 months ago. As of 2026-Q2 that's 3.11 and 3.12.

Reasons:

- 3.11 added meaningful perf wins (~25% faster than 3.10) and fine-grained tracebacks; below 3.11 leaves real value on the table.
- N-1 keeps us from breaking enterprise users on slow upgrade cadences.
- Two versions is the most we test in CI without it getting expensive.

`requires-python = ">=3.11"` in `pyproject.toml`; CI matrix on 3.11 and 3.12. Drop 3.11 the quarter 3.13 turns 6 months old.

Related decision: [[python-dev-tooling]] for the rest of the version-sensitive bits ([[ruff]], [[mypy]] both target the floor).
