# MemoGraph 🧠

[![PyPI version](https://img.shields.io/pypi/v/memograph)](https://pypi.org/project/memograph/)
[![Python Version](https://img.shields.io/pypi/pyversions/memograph)](https://pypi.org/project/memograph/)
[![License](https://img.shields.io/github/license/Indhar01/MemoGraph)](https://github.com/Indhar01/MemoGraph/blob/main/LICENSE)
[![Smithery](https://smithery.ai/badge/@indhar01/memograph)](https://smithery.ai/server/@indhar01/memograph)
[![MCP](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.io)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue)](http://mypy-lang.org/)
[![Tests](https://img.shields.io/badge/tests-pytest-orange)](https://docs.pytest.org/)
[![Code Quality](https://img.shields.io/badge/code%20quality-A+-brightgreen)](https://github.com/Indhar01/MemoGraph)

A graph-based memory system for LLMs with intelligent retrieval. MemoGraph provides a powerful solution to the LLM memory problem by combining knowledge graphs, hybrid retrieval, and semantic search.

## ✨ Features

- **🤖 Smart Auto-Organization Engine**: Automatically extract structured information from memories using LLMs
  - Topics, subtopics, and recurring themes
  - People with roles and organizations
  - Action items with assignees and deadlines
  - Decisions, questions, and sentiment analysis
  - Risks, ideas, and timeline events
- **Graph-Based Memory**: Navigate knowledge using bidirectional wikilinks and backlinks
- **Hybrid Retrieval**: Combines keyword matching, graph traversal, and optional vector embeddings
- **Markdown-Native**: Human-readable markdown files with YAML frontmatter
- **Memory Types**: Support for episodic, semantic, procedural, and fact-based memories
- **Smart Indexing**: Efficient caching system that only re-indexes changed files
- **CLI & Python API**: Use via command line or integrate into your Python applications
- **Multiple LLM Providers**: Works with Ollama, Claude, and OpenAI
- **Context Compression**: Intelligent token budgeting for optimal context windows
- **Salience Scoring**: Memory importance ranking for better retrieval

## 🚀 Quick Start

### Installation

```bash
pip install memograph
```

Install with optional dependencies:

```bash
# For OpenAI support
pip install memograph[openai]

# For Anthropic Claude support
pip install memograph[anthropic]

# For Ollama support
pip install memograph[ollama]

# For embedding support
pip install memograph[embeddings]

# Install everything
pip install memograph[all]
```

### Python Usage

```python
from memograph import MemoryKernel, MemoryType

# Initialize the kernel attached to your vault path
kernel = MemoryKernel("~/my-vault")

# Ingest all notes in the vault
stats = kernel.ingest()
print(f"Indexed {stats['indexed']} memories.")

# Programmatically add a new memory
kernel.remember(
    title="Meeting Note",
    content="Decided to use BFS graph traversal for retrieval.",
    memory_type=MemoryType.EPISODIC,
    tags=["design", "retrieval"]
)

# Retrieve context for an LLM query
context = kernel.context_window(
    query="how does retrieval work?",
    tags=["retrieval"],
    depth=2,
    top_k=8
)

print(context)
```

## 🔌 MCP Server (Model Context Protocol)

MemoGraph includes a full-featured MCP server for seamless integration with AI assistants like **Cline** and **Claude Desktop**.

### 14 Available Tools

| Category | Tools | Description |
|----------|-------|-------------|
| **Search** | `search_vault`, `query_with_context` | Semantic search and context retrieval |
| **Create** | `create_memory`, `import_document` | Add memories and import documents |
| **Read** | `list_memories`, `get_memory`, `get_vault_info` | Browse and retrieve memories |
| **Update** | `update_memory` | Modify existing memories |
| **Delete** | `delete_memory` | Remove memories by ID |
| **Analytics** | `get_vault_stats` | Vault statistics and insights |
| **Discovery** | `list_available_tools` | List all available tools |
| **Autonomous** | `auto_hook_query`, `auto_hook_response`, `configure_autonomous_mode`, `get_autonomous_config` | Autonomous memory management |

### Quick Setup for Cline

Add to your `~/.cline/mcp_settings.json`:

```json
{
  "mcp": {
    "servers": {
      "memograph": {
        "command": "python",
        "args": ["-m", "memograph.mcp.run_server"],
        "env": {
          "MEMOGRAPH_VAULT": "/path/to/your/vault"
        }
      }
    }
  }
}
```

### Quick Setup for Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "memograph": {
      "command": "python",
      "args": ["-m", "memograph.mcp.run_server", "--vault", "/path/to/your/vault"]
    }
  }
}
```

### Usage Examples

Once configured, use natural language with your AI assistant:

```
"Search my vault for memories about Python"
"Create a memory titled 'Project Ideas' with content '...'"
"Update memory abc-123 to have salience 0.9"
"Delete memory xyz-456"
"What tools are available?"
"Get vault statistics"
```

See **[CONFIG_REFERENCE.md](memograph/mcp/CONFIG_REFERENCE.md)** for complete MCP configuration guide.

## 🎯 CLI Usage

MemoGraph comes with a powerful CLI for managing your vault and chatting with it.

### Ingest

Index your markdown files into the graph database:

```bash
memograph --vault ~/my-vault ingest
```

Force re-indexing all files:

```bash
memograph --vault ~/my-vault ingest --force
```

### Remember

Quickly add a memory from the command line:

```bash
memograph --vault ~/my-vault remember \
    --title "Team Sync" \
    --content "Discussed Q3 goals." \
    --tags planning q3
```

### Context Window

Generate context for a query:

```bash
memograph --vault ~/my-vault context \
    --query "What did we decide about the database?" \
    --tags architecture \
    --depth 2 \
    --top-k 5
```

### Ask (Interactive Chat)

Start an interactive chat session with your vault context:

```bash
memograph --vault ~/my-vault ask --chat --provider ollama --model llama3
```

Or ask a single question:

```bash
memograph --vault ~/my-vault ask \
    --query "Summarize our design decisions" \
    --provider claude \
    --model claude-3-5-sonnet-20240620
```

### Diagnostics

Check your environment and connection to LLM providers:

```bash
memograph --vault ~/my-vault doctor
```

## 📖 Core Concepts

### Memory Types

MemoGraph supports different types of memories inspired by cognitive science:

- **Episodic**: Personal experiences and events (e.g., meeting notes)
- **Semantic**: Facts and general knowledge (e.g., documentation)
- **Procedural**: How-to knowledge and processes (e.g., tutorials)
- **Fact**: Discrete factual information (e.g., configuration values)

### Graph Traversal

The library uses BFS (Breadth-First Search) to traverse your knowledge graph:

```python
# Retrieve nodes with depth=2 (2 hops from seed nodes)
nodes = kernel.retrieve_nodes(
    query="graph algorithms",
    depth=2,  # Traverse up to 2 levels deep
    top_k=10  # Return top 10 relevant memories
)
```

### Salience Scoring

Each memory has a salience score (0.0-1.0) that represents its importance:

```yaml
---
title: "Critical Architecture Decision"
salience: 0.9
memory_type: semantic
---

We decided to use PostgreSQL for better ACID guarantees...
```

## 🏗️ Project Structure

```
MemoGraph/
├── memograph/          # Main package
│   ├── core/           # Core functionality
│   │   ├── kernel.py   # Memory kernel
│   │   ├── graph.py    # Graph implementation
│   │   ├── retriever.py # Hybrid retrieval
│   │   ├── indexer.py  # File indexing
│   │   └── parser.py   # Markdown parsing
│   ├── adapters/       # LLM and embedding adapters
│   │   ├── embeddings/ # Embedding providers
│   │   ├── frameworks/ # Framework integrations
│   │   └── llm/        # LLM providers
│   ├── storage/        # Storage and caching
│   ├── mcp/            # MCP server implementation
│   └── cli.py          # CLI implementation
├── tests/              # Test suite
├── examples/           # Example usage
└── scripts/            # Utility scripts
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Indhar01/MemoGraph.git
   cd MemoGraph
   ```

2. Install in development mode:
   ```bash
   pip install -e ".[all,dev]"
   ```

3. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```

4. Run tests:
   ```bash
   pytest
   ```

### Code Quality

We maintain high code quality standards:

- **Linting**: Ruff for fast Python linting
- **Formatting**: Ruff formatter for consistent code style
- **Type Checking**: MyPy for static type analysis
- **Testing**: Pytest with comprehensive test coverage
- **Pre-commit Hooks**: Automated checks before each commit

## 📚 Documentation

- **[AGENTS.md](AGENTS.md)** - Guide for AI agents working with this codebase
- **[Contributing Guide](CONTRIBUTING.md)** - How to contribute to the project
- **[Code of Conduct](CODE_OF_CONDUCT.md)** - Community guidelines
- **[Security Policy](SECURITY.md)** - Security reporting and best practices
- **[Changelog](CHANGELOG.md)** - Version history and changes

## 🔒 Security

See our [Security Policy](SECURITY.md) for reporting vulnerabilities.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🌟 Acknowledgments

Inspired by the need for better memory management in LLM applications. Built with:

- Graph-based knowledge representation
- Hybrid retrieval strategies
- Cognitive science principles

## 📬 Contact & Support

- **Issues**: [GitHub Issues](https://github.com/Indhar01/MemoGraph/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Indhar01/MemoGraph/discussions)

## 🚦 Status

**Current Version**: 0.1.0 (Alpha - Marketplace Ready)

This project is in active development with a focus on code quality and stability:

- ✅ Core functionality is stable and tested
- ✅ All linter checks passing (Ruff)
- ✅ Type checking configured (MyPy)
- ✅ Pre-commit hooks enabled
- ✅ Comprehensive test suite
- ⚠️ API may change in minor versions until v1.0.0

**Recent Improvements**:
- Enhanced code quality with Ruff linting and formatting
- Added comprehensive type checking with MyPy
- Improved project structure and organization
- Updated MCP server with 14 tools including autonomous features
- Added AGENTS.md for AI assistant integration

---

Made with ❤️ for better LLM memory management
