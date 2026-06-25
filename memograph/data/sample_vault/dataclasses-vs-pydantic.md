---
title: dataclass vs Pydantic
memory_type: semantic
tags: [python, modeling, decision]
salience: 0.7
---

Both let you define structured data with [[type-hints]]. They're not interchangeable.

**`@dataclass`** is in the standard library. Zero runtime validation; the annotations are documentation. Use for internal types where you control the construction sites — config objects, return values, event payloads inside the same process.

**Pydantic** validates at construction time, coerces compatible types, and serialises to/from JSON. Use at trust boundaries — HTTP request/response models, config loaded from YAML/env, anything crossing a process boundary. The runtime cost is real but small.

Rough rule: if the data comes from outside your codebase (network, user, file), Pydantic. If it stays inside, dataclass.

`attrs` exists; it's a superset of dataclass with more features. Reach for it when dataclass isn't enough but Pydantic is overkill.
