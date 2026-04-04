# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project-Specific Non-Obvious Patterns

### MCP Setup Critical Issue
- **Python path resolution bug**: MCP clients often can't find the memograph module
- **Solution**: Use `scripts/setup_mcp.py` which creates a wrapper script (`.bat` on Windows, `.sh` on Unix)
- **Why**: MCP clients may use different Python interpreter than where memograph is installed
- **Manual workaround**: Use full Python path in config: `"/full/path/to/python" -m memograph.mcp.run_server`
- **Verification**: `python scripts/setup_mcp.py --verify-only`

### Testing Gotchas
- **Critical**: `populated_kernel` fixture calls `.ingest()` AFTER adding memories (line 50 in tests/conftest.py) - if you create similar fixtures, you MUST do this
- **Stress tests**: Excluded from CI - run explicitly with `pytest tests/stress/` or exclude with `pytest --ignore=tests/stress/`
- **Coverage threshold**: Set to 40% (not the typical 80%)
- **Async mode**: `asyncio_mode = "auto"` in pytest config - don't set it manually in tests
- **Auto-reset fixture**: `reset_environment` in conftest.py auto-runs before each test to reset env vars
- **Warnings as errors**: Pytest treats warnings as errors by default with selective ignores for deprecation warnings

### Code Style Non-Obvious Choices
- **Type unions**: Use `X | Y` syntax, NOT `Union[X, Y]` - ruff rule UP007 is ignored for this
- **Linting exceptions**:
  - `__init__.py` files: F401 (unused imports) allowed for re-exports
  - `temp_*.py` files: ALL rules ignored (for scratch/test files)
- **MCP server coverage**: Files in `memograph/mcp/run_server.py`, `__main__.py`, `mcp_setup.py` excluded from coverage
- **Importer modules excluded**: All files in `memograph/importers/*` excluded from coverage (optional integrations)
- **Pre-commit hooks**: Mypy uses `pass_filenames: false` in .pre-commit-config.yaml - checks entire memograph/ directory, not just changed files

### Optional Features Require Explicit Enablement
- **GAM retrieval**: `MemoryKernel(use_gam=True)` - NOT enabled by default
- **Caching**: `MemoryKernel(enable_cache=True)` - NOT enabled by default
- **Validation**: `MemoryKernel(validate_inputs=True)` - NOT enabled by default
- These are opt-in performance/quality features discovered by reading kernel code

### Legacy Compatibility
- Files `kernel_enhanced.py`, `kernel_async.py`, `kernel_batch.py`, `kernel_gam_async.py`, `graph_enhanced.py` are legacy aliases
- They re-export from consolidated classes for backwards compatibility
- Don't modify these files - update the main implementation instead

### Graph Architecture Patterns
- **In-memory graph**: VaultGraph holds all nodes in memory with bidirectional adjacency lists
- **Critical pattern**: Must call `.ingest()` to populate graph after adding memories to vault
- **Graph reconstruction**: Each `ingest()` call creates new graph from scratch (`self.graph = VaultGraph()` at kernel.py:583) - not incremental updates
- **Auto-ingest on empty graph**: `retrieve_nodes()` automatically calls `ingest()` if graph is empty (kernel.py:1261-1263) - convenient but could be surprising for performance-sensitive code
- **Indexing pattern**: VaultIndexer uses smart caching based on file modification time to avoid re-indexing

### Install Command
- Development: `pip install -e ".[all,dev]"` (note: brackets need quoting in some shells)
- The `[all,dev]` extras install optional LLM providers + dev tools
