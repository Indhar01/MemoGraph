# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MemoGraph is a graph-based memory system for LLMs. It combines knowledge graphs, hybrid retrieval (keyword + semantic + graph traversal), and markdown-native storage to give LLMs persistent, queryable memory. Python 3.10+, MIT licensed.

## Common Commands

```bash
# Install for development
pip install -e ".[all,dev]"
pre-commit install

# Run all tests (stress tests excluded by default in CI)
pytest
pytest --ignore=tests/stress/

# Run a single test file or test by name
pytest tests/test_kernel.py
pytest -k "test_remember"

# Lint and format
ruff check .
ruff check --fix .
ruff format .

# Type checking
mypy memograph/ --config-file=pyproject.toml

# Run all pre-commit hooks
pre-commit run --all-files
```

## Architecture

### Core Pipeline

`MemoryKernel` (core/kernel.py) is the central orchestrator. The flow is:

1. **Ingest**: `VaultIndexer` (core/indexer.py) scans a vault directory for `.md` files, parses YAML frontmatter + wikilinks via `MarkdownParser` (core/parser.py), builds `MemoryNode` objects
2. **Store**: `VaultGraph` (core/graph.py) holds nodes in-memory with bidirectional adjacency lists (wikilinks + backlinks)
3. **Retrieve**: `HybridRetriever` (core/retriever.py) combines keyword matching, optional vector embeddings, and BFS graph traversal with configurable depth/top_k
4. **Compress**: `ContextCompressor` (core/compressor.py) applies token budgeting to fit retrieved nodes into LLM context windows

### Optional Features (built into MemoryKernel)

- **Caching**: Enable with `enable_cache=True` — multi-level embedding cache + query result cache (via `memograph/storage/cache_enhanced.py`)
- **Validation**: Enable with `validate_inputs=True` — input validation with helpful error messages (via `memograph/core/validation.py`)
- **GAM retrieval**: Enable with `use_gam=True` — Graph Attention Memory scoring using `GAMScorer` + `GAMRetriever` (core/gam_scorer.py, core/gam_retriever.py)
- **Batch async**: Methods like `remember_batch_async()`, `retrieve_batch_async()`, `update_batch_async()`, `delete_batch_async()` for concurrent operations
- **Concurrency**: `max_concurrent` parameter controls async semaphore limit

Legacy alias files (`kernel_enhanced.py`, `kernel_async.py`, `kernel_batch.py`, `kernel_gam_async.py`, `graph_enhanced.py`) re-export from the consolidated classes for backwards compatibility.

### Adapter Layer

- **LLM adapters** (adapters/llm/): Claude, Ollama, LiteLLM - pluggable providers for chat/generation
- **Embedding adapters** (adapters/embeddings/): OpenAI, Ollama, SentenceTransformers - pluggable vector embedding providers
- **Framework adapters** (adapters/frameworks/): LangChain and LlamaIndex integrations

### MCP Server

`memograph/mcp/server.py` implements a Model Context Protocol server with 14 tools for AI assistant integration. Entry point: `python -m memograph.mcp.run_server`.

### Web UI

`memograph/web/` contains a FastAPI backend (backend/server.py with route modules) and a React+Vite+Tailwind frontend (frontend/).

### Storage

`memograph/storage/` provides vault file management (vault.py) and index caching (cache.py, cache_enhanced.py) to avoid re-indexing unchanged files.

## Code Conventions

- **Line length**: 100 characters
- **Linting/formatting**: Ruff (config in pyproject.toml + .ruff.toml)
- **Type checking**: MyPy with `ignore_missing_imports = true`; type hints required on public functions; use `X | None` syntax not `Optional[X]`
- **Docstrings**: Google-style (Args, Returns, Raises, Example sections)
- **Logging**: Use `logging.getLogger("memograph")`
- **Commits**: Conventional Commits format (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `chore:`, `ci:`)

## Testing

- Framework: pytest with pytest-asyncio (auto mode), pytest-cov, pytest-benchmark
- Fixtures in `tests/conftest.py`: `temp_vault`, `kernel`, `populated_kernel`
- Markers: `@pytest.mark.slow`, `@pytest.mark.integration`, `@pytest.mark.stress`, `@pytest.mark.benchmark`
- Stress tests live in `tests/stress/` and are excluded from CI runs
- Coverage configured with `--cov=memograph`; threshold is 40%

## Key Public API

The package exports from `memograph/__init__.py`:
- `MemoryKernel` - main entry point for all memory operations
- `MemoryType` / `EntityType` - enums (episodic, semantic, procedural, fact)
- `SmartAutoOrganizer` - LLM-powered entity extraction
- `GAMConfig` / `GAMScorer` / `GAMRetriever` - attention-based retrieval
- `AccessTracker` - tracks memory access patterns

CLI entry point: `memograph` command (defined in pyproject.toml as `memograph.cli:main`).
