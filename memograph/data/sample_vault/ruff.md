---
title: ruff
memory_type: semantic
tags: [python, tooling, linting]
salience: 0.75
---

`ruff` is a Rust-based Python linter and formatter that subsumes most of flake8, black, isort, pyupgrade, and pylint. Fast enough to run on every save.

Two commands cover 95% of usage:

- `ruff check .` — lint; `--fix` auto-applies safe fixes.
- `ruff format .` — formatter, drop-in for black.

Configure in `pyproject.toml` under `[tool.ruff]`. Sane defaults: `line-length = 100`, enable rule sets `E`, `F`, `I`, `B`, `UP` to start.

Pair with [[mypy]] for type checking and `pre-commit` to enforce both at commit time. See [[python-dev-tooling]] for the full setup.
