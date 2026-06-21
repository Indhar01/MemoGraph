---
title: mypy
memory_type: semantic
tags: [python, types, tooling]
salience: 0.7
---

`mypy` statically checks [[type-hints]] in Python code. Configure it in `pyproject.toml` under `[tool.mypy]`. Useful flags:

- `strict = true` — turns on every check; the right default for new projects.
- `ignore_missing_imports = true` — silences false positives from libraries without stubs.
- Per-module overrides under `[[tool.mypy.overrides]]` for relaxing rules where the cost-benefit isn't there yet.

Iteration loop: `mypy <pkg>/` runs in seconds on warm cache. CI should fail on any new error. When you can't fix a real warning immediately, `# type: ignore[<error-code>]` localizes the suppression — never blanket-ignore.

For rapid prototyping use [[ruff]] first; it catches the cheap stuff faster.
