# MemoGraph Roadmap

Product improvement plan for MemoGraph — a graph-based memory system for LLMs.

## Completed

### v0.2.0 — Core Consolidation (Done)

- [x] Merged 5 kernel variants into single `MemoryKernel` with optional `enable_cache`, `validate_inputs`, `max_concurrent`, `use_gam` params
- [x] Merged `EnhancedVaultGraph` into `VaultGraph` with O(1) tag/type/backlink indexes
- [x] Single version source of truth (`pyproject.toml` via `importlib.metadata`)
- [x] Backwards-compat aliases for all old imports (`EnhancedMemoryKernel`, `AsyncMemoryKernel`, `BatchMemoryKernel`, `GAMAsyncKernel`, `EnhancedVaultGraph`)
- [x] Fixed all documentation inconsistencies (AGENTS.md tool counts, version refs)
- [x] Fixed pre-existing syntax bugs in `action_logger.py` and `web/backend/routes/memories.py`
- [x] Net result: -2,837 lines deleted, +1,531 added

### v0.3.0 — MCP & Quality (Done)

**MCP bug fixes (all 8 fixed):**
- [x] Added 4 missing autonomous tools to `handle_call_tool()` routing
- [x] Added auto-ingest on MCP server startup
- [x] Fixed `delete_memory` to use `graph.remove_node()` instead of `._nodes.pop()`
- [x] Removed dead `server_enhanced.py`
- [x] Updated `cline_config.json` tool count
- [x] Fixed `import_document` broken import (replaced with direct file reading)
- [x] Fixed hardcoded server version to use `memograph.__version__`

**MCP competitive features (all implemented):**
- [x] MCP Resources — memories browsable via `memograph://vault/{id}` and `memograph://tag/{tag}` URIs
- [x] MCP Resource Templates for parameterized access
- [x] MCP Prompts — `vault-summary`, `recall`, `weekly-review`, `find-connections`
- [x] `relate_memories` tool — create wikilinks between memories
- [x] `search_by_graph` tool — traverse graph from a memory within N hops
- [x] `find_path` tool — BFS shortest path between two memories
- [x] `bulk_create` tool — create multiple memories in one call
- [x] Wikilink suggestions in `create_memory` response (`suggested_links` field)
- [x] MCP server now uses all 3 MCP capabilities: Tools (19), Resources, Prompts

**Test coverage:**
- [x] 43 MCP server tests (tool routing, CRUD, autonomous hooks, graph tools, bulk create)
- [x] 18 MemoryNode tests (serialization, deserialization, roundtrip)
- [x] 26 metrics/action logger tests
- [x] 11 compressor/assistant tests
- [x] 10 CLI tests (ingest, remember, context, doctor)
- [x] 6 logging config tests
- [x] 20 graph tests (find_path, tag/type indexes, stats)
- [x] Coverage: 46.94% -> **72.87%**

### v0.3.1 — Scaling & Web (Done)

**Scaling benchmarks (`tests/test_scaling.py`):**
- [x] Benchmarks at 100, 1K, and 10K note scales
- [x] Ingest: 522 notes/sec (100), 354 notes/sec (1K), ~81 notes/sec (10K)
- [x] Query: 0.5ms avg (100), 8.2ms avg (1K), 107ms avg (10K)
- [x] Graph traversal: <0.1ms at 1K
- [x] Memory footprint tracking

**Web UI integration:**
- [x] Added `[web]` extra to `pyproject.toml` (`pip install memograph[web]`)
- [x] Removed separate `memograph/web/requirements.txt`
- [x] Fixed Pydantic V2 deprecation (`schema_extra` -> `json_schema_extra`)
- [x] 14 web API tests (health, CRUD, search, graph, analytics)

**Final numbers: 417 tests, 72.87% coverage, lint/format clean**

---

## Current State

| Metric | Value |
|--------|-------|
| Tests | 417 passing, 15 skipped |
| Coverage | 72.87% |
| MCP Tools | 19 |
| MCP Resources | Yes (vault + tag browsing) |
| MCP Prompts | 4 (vault-summary, recall, weekly-review, find-connections) |
| Supported scales | 1K notes comfortably, 10K usable |
| Python | 3.10, 3.11, 3.12 |

---

## Remaining Work

### v0.4.0 — Polish & Performance

- [ ] **Documentation site** — MkDocs with mkdocstrings for auto-generated API docs. Structure: Getting Started, Python API, CLI Reference, MCP Server Guide, Architecture
- [ ] **Frontend CI pipeline** — add `npm run build` and `npm run lint` to CI workflow for `memograph/web/frontend/`
- [ ] **Optimize 10K ingest** — the 10K note ingest takes ~2 min, bottlenecked by sequential file I/O. Consider parallel file reading or incremental ingest
- [ ] **Persistent graph backend** — optional SQLite-backed graph for vaults >5K notes to avoid full re-ingest on restart
- [ ] **MCP notifications** — send `resources/updated` notifications when memories are created/updated/deleted so clients stay in sync

### v1.0.0 — Stable Release

- [ ] Stable public API with semantic versioning and deprecation policy
- [ ] 80%+ test coverage
- [ ] Published documentation site
- [ ] Performance benchmarks in CI with regression detection
- [ ] Smithery listing verified and installable
- [ ] PyPI release with all extras working (`pip install memograph[all]`, `pip install memograph[web]`)
