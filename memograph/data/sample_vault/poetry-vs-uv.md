---
title: Poetry vs uv (2026 read)
memory_type: episodic
tags: [python, tooling, decision]
salience: 0.6
---

Notes from picking between Poetry and uv for a new project this quarter.

**uv (Astral)** — Rust-based; same shop as [[ruff]]. Resolver is 10-100× faster than pip's. `uv pip compile` produces hash-pinned lockfiles that work with any pip-compatible toolchain. Sticks close to PEP 621 / pyproject.toml; no proprietary lockfile format.

**Poetry** — Mature, opinionated, has its own lockfile (`poetry.lock`) and dependency-spec syntax. Slower resolves, but the publishing flow (`poetry publish`) is smooth.

Picked uv for this project because: speed of CI matters; lockfile portability matters more (any future contributor with `pip` can install). Poetry's publishing convenience didn't outweigh those.

This may flip — uv is moving fast. Decision rationale belongs in [[python-dev-tooling]].
