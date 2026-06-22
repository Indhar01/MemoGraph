---
title: pytest patterns
memory_type: procedural
tags: [python, testing, patterns]
salience: 0.8
---

The pytest moves I reach for in every project:

- **Fixtures over `setUp`** — composable, scope-aware, dependency-injected. `@pytest.fixture(scope="session")` for expensive setup like a DB.
- **Parametrize aggressively.** `@pytest.mark.parametrize` collapses 10 near-duplicate tests into one with a parameter table.
- **`tmp_path` for filesystem tests.** Pytest gives you a per-test temp dir for free; never use `/tmp/foo` literals.
- **`monkeypatch` for env vars and module attrs.** Auto-undone at test exit.
- **`-k <expr>` and `-m <marker>`** to slice the suite when iterating.

Avoid mocks where a real object is cheap (e.g. SQLite-in-memory beats mocking SQLAlchemy). When you do mock, mock at the boundary you control, not the third-party library's internals — those interfaces drift.

For async code, `pytest-asyncio` plus `asyncio_mode = "auto"` removes the `@pytest.mark.asyncio` boilerplate. Related: [[python-async]].
