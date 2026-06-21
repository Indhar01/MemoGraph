---
title: Type hints
memory_type: semantic
tags: [python, types, fundamentals]
salience: 0.85
---

Python type hints are runtime-optional annotations checked statically by [[mypy]] (or pyright/pyre/pylance). They cost nothing at runtime — the interpreter ignores them — and pay back hugely as a codebase grows.

The 80/20: annotate function signatures (`def f(x: int) -> str`), don't bother annotating local variables unless mypy complains. Use `from __future__ import annotations` in files that import-cycle so type names are strings.

For data classes, `dataclass`-with-annotated-fields is the path of least resistance. Pydantic models also rely on annotations.

When inheritance gets weird, `typing.Protocol` and `typing.TypeVar` carry most of the load. See [[mypy]] for tooling and [[ruff]] for the lint pass that catches missing annotations early.
