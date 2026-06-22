# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is MemoGraph

MemoGraph is a graph-based memory system for LLMs. It stores memories as markdown files in a "vault" directory, builds a knowledge graph from wikilinks (`[[title]]`) and YAML frontmatter, and exposes retrieval via a Python API, CLI, MCP server, and web UI.

## Commands

### Python environment
```bash
pip install -e ".[dev]"          # Install with all dev dependencies
pip install -e ".[all]"          # Install with all optional features
pip install -e ".[embeddings]"   # Add sentence-transformers / numpy
pip install -e ".[web]"          # Add FastAPI / uvicorn
pip install -e ".[integrations]" # Add Obsidian / Notion watchers
```

### Testing
```bash
pytest                                    # Run all tests
pytest tests/test_graph.py                # Run a single test file
pytest tests/test_graph.py::test_foo      # Run a single test function
pytest -m "not slow and not integration"  # Skip slow / integration tests
pytest -m unit                            # Only unit tests
pytest --no-cov                           # Skip coverage (faster)
```

Test layout: top-level `tests/` holds unit tests for each module; subfolders `tests/ai/`, `tests/swarm/`, `tests/integrations/`, `tests/integration_suite/`, and `tests/stress/` group their respective slower or feature-gated suites. `pytest.ini_options` auto-injects `--cov`, so use `--no-cov` for fast iteration. Available markers: `unit`, `slow`, `integration`, `stress`, `benchmark`, `load`.

### Linting and formatting
```bash
ruff check .           # Lint
ruff check . --fix     # Lint and auto-fix
ruff format .          # Format (line length 100)
mypy memograph/        # Type-check
```

### Running the MCP server
```bash
python -m memograph.mcp.run_server --vault ~/my-vault
python -m memograph.mcp.run_server --vault ~/my-vault --provider claude --model claude-sonnet-4-6
# Or via env vars:
MEMOGRAPH_VAULT=~/my-vault python -m memograph.mcp.run_server
```

### Running the web UI
```bash
python -m memograph.web.run_web_ui --vault ~/my-vault   # Start backend (FastAPI)
cd memograph/web/frontend && npm run dev                 # Start Vite dev server
cd memograph/web/frontend && npm run build               # Production build
```

### CLI
```bash
memograph --help
memograph add --title "My Note" --content "..." --type semantic --tags foo,bar
memograph search "python tips"
memograph list --type episodic
```

The CLI entry point is `memograph.cli:main`; argument parsing and command bodies are split across `cli.py`, `cli_helpers.py`, `cli_batch_helpers.py`, and `cli_infrastructure_helpers.py` (all listed under `mypy` `ignore_errors` overrides — don't expect type-check coverage there).

### Local CI / pre-push

`scripts/run_ci_locally.ps1` mirrors the GitHub Actions checks; `scripts/setup_pre_push_hook.ps1` installs `scripts/pre-push.ps1` as a git hook. See `LOCAL_CI_GUIDE.md` and `scripts/PRE-PUSH-GUIDE.md` for what runs and how to bypass safely.

## Architecture

### Storage layer (`memograph/storage/`)
- **`vault.py` — `VaultStorage`**: thin wrapper that maps a root directory to markdown files. Reads/writes `.md` files; no database.
- **`cache.py` / `cache_enhanced.py`**: disk caches (JSON) for mtime, embeddings, and graph state, stored inside the vault as `.memograph_cache.json`, `.memograph_graph.json`, `.memograph_embeddings.json`.

### Core layer (`memograph/core/`)
Data flows: `VaultStorage` → `parser.parse_file` → `MemoryNode` → `VaultGraph` → `VaultIndexer` → `MemoryKernel`.

- **`node.py` — `MemoryNode`**: the unit of memory. Holds title, content, `MemoryType` (episodic/semantic/procedural/fact), salience (0–1), wikilinks, backlinks, tags, and an optional embedding vector.
- **`parser.py`**: reads markdown + YAML frontmatter. Extracts `[[wikilinks]]` via regex, builds `MemoryNode`. Returns `None` on parse failure.
- **`graph.py` — `VaultGraph`**: in-memory adjacency structure. O(1) lookups by ID, tag, and type. Maintains forward links and backlinks. Does not persist itself — `VaultIndexer` handles serialization.
- **`indexer.py` — `VaultIndexer`**: watches vault for file changes (mtime cache), re-parses changed files, updates `VaultGraph`. Also manages embedding caching.
- **`retriever.py` — `HybridRetriever`**: combines graph traversal (BFS from seed nodes), metadata filtering (tags, type, salience), and optional vector re-ranking.
- **`gam_retriever.py` / `gam_scorer.py`**: Graph Attention Memory — extends retrieval with attention-weighted graph scoring.
- **`kernel.py` — `MemoryKernel`**: the main API surface. `remember()` writes a new markdown node; `search()` / `context_window()` retrieve; `ingest()` / `ingest_async()` reindex the vault. Also exposes a fluent `MemoryQuery` builder.
- **`kernel_async.py`, `kernel_batch.py`, `kernel_enhanced.py`, `kernel_gam_async.py`**: specialized kernel variants (async, batch, GAM-enabled).
- **`config.py` — `MemographConfig`**: reads/writes `~/.memograph/config.yaml`. Supports named profiles.
- **`compressor.py`**: token-budget-aware context compression for `context_window()`.
- **`extractor.py` — `SmartAutoOrganizer`**: heuristic entity and tag extraction from note content.

### MCP layer (`memograph/mcp/`)
Exposes the vault as an MCP server (stdio) for Claude Desktop, Cline, etc.

- **`server.py` — `MemoGraphMCPServer`**: wraps `MemoryKernel`, implements all tool handlers (search, create, update, delete, graph ops, analytics, swarm ops).
- **`run_server.py`**: CLI entry point. Registers MCP tools/resources/prompts with the official `mcp` SDK and runs `stdio_server`.
- **`run_server_enhanced.py`**: variant with extra analytics tools.
- **`autonomous_hooks.py` — `AutonomousHooks`**: `auto_hook_query` / `auto_hook_response` tools for AI assistants to auto-save conversation exchanges to the vault.
- **`conversation_monitor.py` — `ConversationMonitor`**: background monitor that detects unsaved conversation turns.

### Swarm layer (`memograph/swarm/`)
Autonomous ACO (Ant Colony Optimization) agents that curate the vault in the background.

- **`orchestrator.py` — `SwarmOrchestrator`**: schedules agents, runs cycles, persists pheromone trails and cycle reports.
- **`pheromone.py` — `PheromoneMap`**: ACO pheromone trails guide agents toward under-visited nodes.
- **`agents/`**: five agents — `TaggerAgent`, `LinkerAgent`, `GapAgent`, `SalienceAgent`, `SummarizerAgent`. Each processes a batch of nodes per cycle.
- **`config.py` — `SwarmConfig`**: per-agent config (`AgentConfig`) and global scheduling/safety settings.
- Swarm is activated by passing `enable_swarm=True` to `MemoryKernel`.

### AI layer (`memograph/ai/`)
Optional AI-assisted operations (require an LLM adapter):

- `auto_tagger.py`, `link_suggester.py`, `gap_detector.py`, `content_analyzer.py`

### Web layer (`memograph/web/`)
- **Backend**: FastAPI app (`web/backend/server.py`) with routes under `web/backend/routes/` (memories, search, graph, analytics, AI, actions).
- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + D3/react-force-graph-2d for graph visualization.

### Adapters (`memograph/adapters/`)
Pluggable adapters for embeddings (`sentence-transformers`, `openai`, `ollama`) and LLMs (`claude`, `ollama`, `litellm`). Imported optionally — missing dependencies just disable the feature.

### Integrations (`memograph/integrations/`)
- **Obsidian**: two-way sync with conflict resolution and file watcher.
- **Notion**: OAuth import of Notion pages into the vault.

### Importers (`memograph/importers/`)

One-shot bulk importers separate from `integrations/` — `chatgpt.py` and `claude.py` ingest exported chat archives, `documents.py` ingests TXT/PDF/DOCX. `chat_models.py` defines the shared chat schema. Excluded from coverage in `pyproject.toml`.

### Server schemas (`memograph/server/`)

`schemas.py` holds Pydantic schemas shared between the MCP server and the FastAPI web backend. Keep request/response models here so both surfaces stay in sync.

## Key design decisions

- **Vault = a directory of markdown files.** Every `MemoryNode` is backed by a `.md` file with YAML frontmatter. The vault is human-readable and portable — no proprietary database.
- **Wikilinks are the graph edges.** `[[Title]]` syntax in note content becomes edges in `VaultGraph`.
- **Salience (0–1) decays and boosts.** `AccessTracker` boosts salience on read; `SalienceAgent` (swarm) normalizes it over time.
- **MCP tools mirror the `MemoryKernel` API.** When adding a new kernel method, add a corresponding MCP tool in `server.py` and register the dispatch in `run_server.py`.
- **Async variants exist alongside sync.** The base `MemoryKernel` is sync; `kernel_async.py` provides `async def` wrappers. MCP server always uses the async path.
