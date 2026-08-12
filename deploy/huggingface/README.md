---
title: MemoGraph Demo
emoji: 🧠
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: Try MemoGraph — graph-based memory for LLMs — without installing anything.
tags:
  - mcp
  - memory
  - llm
  - knowledge-graph
  - rag
---

# MemoGraph Demo Space

This is a **read-only public demo** of [MemoGraph](https://github.com/Indhar01/MemoGraph),
a graph-based memory system for LLMs that turns a folder of markdown
notes into a queryable, AI-ready knowledge graph.

## What you can do here

- Browse the sample vault that ships with `memograph quickstart` — 15
  interconnected notes about Python development.
- Run hybrid retrieval queries (keyword + semantic + graph traversal).
- Visualise the wikilink graph.
- Inspect the OpenAPI contract at `/api/docs`.

## What you can't do here

Writes are disabled (`MEMOGRAPH_READONLY=true`). The vault resets on every
container restart. To create, edit, or delete memories, install MemoGraph
locally:

```bash
pip install memograph
memograph quickstart
```

…or wire it into your AI assistant via the
[MCP server](https://github.com/Indhar01/MemoGraph/blob/main/docs/MCP_CLIENTS.md).

## Links

- [GitHub repository](https://github.com/Indhar01/MemoGraph)
- [PyPI package](https://pypi.org/project/memograph/)
- [Documentation](https://indhar01.github.io/MemoGraph/)
- [Discussions](https://github.com/Indhar01/MemoGraph/discussions)
