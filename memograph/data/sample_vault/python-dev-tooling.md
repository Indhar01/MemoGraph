---
title: Python dev tooling baseline
memory_type: procedural
tags: [python, tooling, setup]
salience: 0.9
---

The minimum tooling I install on day one of a new Python project, in this order:

1. **`uv` or `pip-tools`** — for dependency resolution and lockfiles. `uv pip compile` is now my default.
2. **`pytest`** — testing. Add `pytest-cov` for coverage. Mark slow tests with `@pytest.mark.slow`.
3. **[[ruff]]** — lint + format. Replaces black, isort, flake8.
4. **[[mypy]]** — type checking. Strict mode on greenfield projects.
5. **`pre-commit`** — runs ruff + mypy on every commit. Cheap quality gate.

For a new package layout, `pyproject.toml` (PEP 621) is canonical; no more `setup.py` unless you have a specific reason.

CI just runs the same four tools. If `pre-commit run --all-files` and `pytest` pass locally, CI will pass too.

Related: [[type-hints]] for the type system, [[testing-pytest]] for testing patterns, [[poetry-vs-uv]] for the lockfile-tool decision.
