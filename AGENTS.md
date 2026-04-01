# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview

**MemoGraph** is a graph-based memory system for Large Language Models (LLMs) that solves the memory problem through knowledge graphs, hybrid retrieval, and semantic search. It enables LLMs to maintain persistent, queryable memory across conversations.

### Core Purpose
- Provide persistent memory for LLM applications
- Enable intelligent retrieval through graph traversal and semantic search
- Support multiple memory types (episodic, semantic, procedural, fact-based)
- Offer both Python API and CLI interfaces

### Key Technologies
- **Language**: Python 3.10+
- **Storage**: Markdown files with YAML frontmatter
- **Graph**: Custom in-memory graph implementation with BFS traversal
- **Retrieval**: Hybrid approach (keyword + semantic + graph)
- **Optional**: Vector embeddings (sentence-transformers, OpenAI, Ollama)
- **LLM Integration**: Supports Ollama, Claude, OpenAI via adapters
- **MCP Server**: Model Context Protocol for AI assistant integration

## Architecture

### Core Components

1. **MemoryKernel** (`memograph/core/kernel.py`)
   - Central orchestrator for all memory operations
   - Manages graph, indexer, and retriever instances
   - Provides both sync and async APIs
   - Supports GAM (Graph Attention Memory) for enhanced retrieval

2. **VaultGraph** (`memograph/core/graph.py`)
   - In-memory graph structure storing MemoryNode objects
   - Handles bidirectional wikilinks and backlinks
   - Supports entity extraction results storage

3. **HybridRetriever** (`memograph/core/retriever.py`)
   - Combines keyword matching, semantic search, and graph traversal
   - BFS-based graph exploration with configurable depth
   - Optional GAMRetriever subclass for attention-based scoring

4. **VaultIndexer** (`memograph/core/indexer.py`)
   - Scans vault directory for markdown files
   - Parses YAML frontmatter and extracts wikilinks
   - Implements smart caching to avoid re-indexing unchanged files

5. **SmartAutoOrganizer** (`memograph/core/extractor.py`)
   - LLM-powered entity extraction from memories
   - Extracts topics, people, action items, decisions, questions, risks
   - Optional feature requiring LLM client

### Design Patterns

- **Builder Pattern**: `MemoryQuery` class for fluent query construction
- **Adapter Pattern**: Pluggable LLM and embedding providers
- **Factory Methods**: `from_config()`, `from_env()` for kernel initialization
- **Async/Await**: Full async support for FastAPI integration
- **Dataclasses**: Used for configuration (`SearchOptions`, `GAMConfig`)

## Development Workflow

### Setup

```bash
# Clone and setup
git clone https://github.com/Indhar01/MemoGraph.git
cd MemoGraph

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install in development mode
pip install -e ".[all,dev]"

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=memograph --cov-report=html

# Run specific test file
pytest tests/test_kernel.py

# Run tests matching pattern
pytest -k "test_remember"
```

### Code Quality

```bash
# Format code (auto-fix)
ruff format .

# Lint code
ruff check .

# Fix auto-fixable issues
ruff check --fix .

# Type check
mypy memograph/

# Run all pre-commit hooks
pre-commit run --all-files
```

## Coding Conventions

### Style Guidelines

- **Line Length**: 100 characters maximum
- **Type Hints**: Required for all public functions and methods
- **Docstrings**: Google-style docstrings with Args, Returns, Raises, Example sections
- **Imports**: Organized by ruff/isort (stdlib, third-party, local)
- **Naming**:
  - Classes: PascalCase
  - Functions/methods: snake_case
  - Constants: UPPER_SNAKE_CASE
  - Private members: _leading_underscore

### Type Annotations

Always use type hints:

```python
def retrieve_nodes(
    self,
    query: str,
    tags: list[str] | None = None,
    depth: int = 2,
    top_k: int = 8,
) -> list[MemoryNode]:
    """Retrieve relevant memory nodes."""
    ...
```

Use modern union syntax (`|`) instead of `Union` from typing.

### Docstring Format

```python
def context_window(
    self,
    query: str,
    token_limit: int = 2048,
) -> str:
    """Retrieve relevant context as a compressed string.

    This method combines retrieval and token compression to generate
    a context window suitable for LLM prompts.

    Args:
        query: Search query string to find relevant memories.
        token_limit: Maximum number of tokens in compressed output.

    Returns:
        Compressed string representation of relevant memories.

    Raises:
        ValueError: If query is empty.

    Example:
        >>> kernel = MemoryKernel(vault_path="./vault")
        >>> context = kernel.context_window("python tips", token_limit=1024)
    """
    ...
```

### Error Handling

- Use specific exception types (ValueError, TypeError, RuntimeError)
- Provide clear error messages with context
- Log errors using the `logger` instance
- Validate inputs early in functions

```python
if not query or not isinstance(query, str):
    raise TypeError(f"query must be a non-empty string, got {type(query).__name__}")

if not query.strip():
    raise ValueError("query cannot be empty")
```

### Logging

Use the module-level logger:

```python
import logging

logger = logging.getLogger("memograph")

# Usage
logger.debug("Detailed debug information")
logger.info("General information")
logger.warning("Warning message")
logger.error("Error occurred")
```

## Testing Conventions

### Test Structure

- Place tests in `tests/` directory
- Name test files as `test_*.py`
- Use descriptive test names: `test_<functionality>_<expected_behavior>`
- Use pytest fixtures from `conftest.py`

### Common Fixtures

```python
def test_remember_creates_file(kernel: MemoryKernel, temp_vault: Path):
    """Test that remember() creates a markdown file."""
    path = kernel.remember("Test", "Content")
    assert Path(path).exists()
```

Available fixtures:
- `temp_vault`: Temporary directory for testing
- `kernel`: Empty MemoryKernel instance
- `populated_kernel`: Kernel with test memories pre-loaded

### Test Categories

Use pytest markers:

```python
@pytest.mark.slow
def test_large_vault_indexing():
    """Test indexing a large vault (slow)."""
    ...

@pytest.mark.integration
def test_ollama_integration():
    """Test integration with Ollama backend."""
    ...
```

## Common Tasks

### Adding a New Memory Type

1. Update `MemoryType` enum in `memograph/core/enums.py`
2. Update parser logic if needed
3. Add tests for the new type
4. Update documentation

### Adding a New LLM Adapter

1. Create adapter in `memograph/adapters/llm/`
2. Implement required interface (e.g., `generate()` method)
3. Add optional dependency to `pyproject.toml`
4. Add tests in `tests/`
5. Update documentation

### Adding a New Retrieval Strategy

1. Extend `HybridRetriever` or create new retriever class
2. Implement `retrieve()` method
3. Add configuration options if needed
4. Add tests comparing with existing strategies
5. Update `MemoryKernel` to support new strategy

### Modifying Graph Structure

- Graph modifications should maintain bidirectional links
- Update both `_adjacency` and backlinks
- Ensure thread-safety if adding concurrent access
- Add migration logic if changing serialization format

## File Organization

### Important Files

- `memograph/core/kernel.py`: Main API entry point
- `memograph/core/graph.py`: Graph data structure
- `memograph/core/retriever.py`: Retrieval algorithms
- `memograph/core/indexer.py`: File indexing logic
- `memograph/cli.py`: Command-line interface
- `memograph/mcp/server.py`: MCP server implementation
- `pyproject.toml`: Project configuration and dependencies
- `tests/conftest.py`: Shared test fixtures

### Directory Structure

```
memograph/
├── core/           # Core functionality (kernel, graph, retriever)
├── adapters/       # LLM and embedding adapters
│   ├── embeddings/ # Embedding providers
│   ├── frameworks/ # Framework integrations (LangChain, LlamaIndex)
│   └── llm/        # LLM providers (Claude, Ollama, OpenAI)
├── storage/        # Storage and caching
├── mcp/            # MCP server implementation
└── web/            # Web UI (FastAPI + React)
```

## Commit Message Guidelines

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Adding or updating tests
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `chore`: Maintenance tasks
- `ci`: CI/CD changes

### Examples

```
feat: add GAM-based retrieval scoring

Implements Graph Attention Memory (GAM) scoring that considers
relationship strength, co-access patterns, and temporal decay.

Closes #45

---

fix: handle malformed YAML frontmatter gracefully

Parser now logs warnings instead of crashing when encountering
invalid frontmatter in markdown files.

---

docs: add examples for async API usage

Added comprehensive examples showing FastAPI integration with
async methods like remember_async() and retrieve_nodes_async().
```

## Performance Considerations

### Indexing

- Use `force=False` (default) to leverage caching
- Only re-index changed files based on modification time
- Consider batch operations for large imports

### Retrieval

- Adjust `depth` parameter based on graph size (default: 2)
- Use `top_k` to limit result set size (default: 8)
- Enable embeddings only when semantic search is needed
- Consider GAM for frequently accessed vaults

### Memory Usage

- Graph is stored in-memory; consider size for large vaults
- Embeddings are cached to disk to avoid recomputation
- Use token compression for large context windows

## Security Considerations

- Validate all user inputs (queries, file paths, tags)
- Sanitize file paths to prevent directory traversal
- Use safe YAML loading (`yaml.safe_load()`)
- Avoid executing arbitrary code from memory content
- Validate LLM responses before processing

## Integration Patterns

### FastAPI Integration

```python
from fastapi import FastAPI
from memograph import MemoryKernel

app = FastAPI()
kernel = MemoryKernel(vault_path="./vault")

@app.on_event("startup")
async def startup():
    await kernel.ingest_async()

@app.post("/search")
async def search(query: str):
    nodes = await kernel.retrieve_nodes_async(query)
    return [{"title": n.title, "content": n.content} for n in nodes]
```

### LangChain Integration

```python
from memograph.adapters.frameworks.langchain import MemoGraphRetriever

retriever = MemoGraphRetriever(kernel=kernel)
# Use with LangChain chains
```

### MCP Server

The MCP server provides 14 tools for AI assistants:
- Search: `search_vault`, `query_with_context`
- Create: `create_memory`, `import_document`
- Read: `list_memories`, `get_memory`, `get_vault_info`
- Update: `update_memory`
- Delete: `delete_memory`
- Analytics: `get_vault_stats`
- Discovery: `list_available_tools`
- Autonomous: `auto_hook_query`, `auto_hook_response`, `configure_autonomous_mode`, `get_autonomous_config`

## MCP Server Setup and Troubleshooting

### Common MCP Issues

**Problem: "Module not found" or MCP tools not appearing**

The most common issue with MCP setup is Python path resolution. The MCP client may use a different Python interpreter than where memograph is installed.

**Solutions:**

1. **Use Full Python Path (Recommended)**
   ```json
   {
     "mcpServers": {
       "memograph": {
         "command": "/full/path/to/python",
         "args": ["-m", "memograph.mcp.run_server"],
         "env": {"MEMOGRAPH_VAULT": "/path/to/vault"}
       }
     }
   }
   ```

2. **Use Wrapper Script (Most Reliable)**
   ```bash
   # Run the setup script
   python scripts/setup_mcp.py --client bob --vault ~/my-vault
   ```

   This creates a wrapper script that ensures the correct Python environment is used.

3. **Find Your Python Path**
   ```bash
   # Windows
   where python

   # macOS/Linux
   which python
   ```

**Verification:**
```bash
# Test the command manually
/full/path/to/python -m memograph.mcp.run_server --help

# Run verification
python scripts/setup_mcp.py --verify-only
```

**For detailed troubleshooting**, see [docs/MCP_TROUBLESHOOTING.md](docs/MCP_TROUBLESHOOTING.md)

### MCP Setup for Bob-Shell

To integrate MemoGraph with Bob-Shell:

1. **Automated Setup (Recommended)**
   ```bash
   python scripts/setup_mcp.py --client bob --vault ~/memograph-vault
   ```

2. **Manual Configuration**

   Add to Bob-Shell's MCP configuration file:
   ```json
   {
     "mcp": {
       "servers": {
         "memograph": {
           "command": "/full/path/to/python",
           "args": ["-m", "memograph.mcp.run_server"],
           "env": {
             "MEMOGRAPH_VAULT": "/path/to/vault"
           }
         }
       }
     }
   }
   ```

3. **Verify Setup**
   ```bash
   python scripts/setup_mcp.py --verify-only
   ```

### MCP Tools Available

The MCP server provides 14 tools organized in categories:
- **Search**: `search_vault`, `query_with_context`
- **Create**: `create_memory`, `import_document`
- **Read**: `list_memories`, `get_memory`, `get_vault_info`
- **Update**: `update_memory`
- **Delete**: `delete_memory`
- **Analytics**: `get_vault_stats`
- **Discovery**: `list_available_tools`
- **Autonomous**: `auto_hook_query`, `auto_hook_response`, `configure_autonomous_mode`, `get_autonomous_config`

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Run `pip install -e ".[all,dev]"` |
| Pre-commit hooks fail | Run `pre-commit run --all-files` |
| Tests fail with Ollama | Ensure Ollama is running: `ollama serve` |
| Type errors in editor | Install mypy language server extension |
| Slow indexing | Use `force=False` to enable caching |
| Empty retrieval results | Check if `ingest()` was called |

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Additional Resources

- **README**: Project overview and quick start
- **CONTRIBUTING**: Detailed contribution guidelines
- **CHANGELOG**: Version history and changes
- **SECURITY**: Security policy and reporting
- **docs/**: Additional documentation and guides
- **examples/**: Usage examples and patterns

## Version Information

- **Current Version**: 0.0.2 (Alpha)
- **Python Support**: 3.10, 3.11, 3.12
- **License**: MIT
- **Status**: Active development (API may change before v1.0.0)
