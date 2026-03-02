# Mnemo Vault 🧠

[![PyPI version](https://img.shields.io/pypi/v/mnemo-vault)](https://pypi.org/project/mnemo-vault/)
[![Python Version](https://img.shields.io/pypi/pyversions/mnemo-vault)](https://pypi.org/project/mnemo-vault/)
[![License](https://img.shields.io/github/license/Indhar01/Mnemo-Vault)](https://github.com/Indhar01/Mnemo-Vault/blob/main/LICENSE)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

A graph-based memory vault for LLMs with intelligent retrieval. Mnemo Vault provides a powerful solution to the LLM memory problem by combining knowledge graphs, hybrid retrieval, and semantic search.

## ✨ Features

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
pip install mnemo-vault
```

Install with optional dependencies:

```bash
# For OpenAI support
pip install mnemo-vault[openai]

# For Anthropic Claude support
pip install mnemo-vault[anthropic]

# For Ollama support
pip install mnemo-vault[ollama]

# For embedding support
pip install mnemo-vault[embeddings]

# Install everything
pip install mnemo-vault[all]
```

### Python Usage

```python
from mnemo import MemoryKernel, MemoryType

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

## 🎯 CLI Usage

Mnemo comes with a powerful CLI for managing your vault and chatting with it.

### Ingest

Index your markdown files into the graph database:

```bash
mnemo --vault ~/my-vault ingest
```

Force re-indexing all files:

```bash
mnemo --vault ~/my-vault ingest --force
```

### Remember

Quickly add a memory from the command line:

```bash
mnemo --vault ~/my-vault remember \
    --title "Team Sync" \
    --content "Discussed Q3 goals." \
    --tags planning q3
```

### Context Window

Generate context for a query:

```bash
mnemo --vault ~/my-vault context \
    --query "What did we decide about the database?" \
    --tags architecture \
    --depth 2 \
    --top-k 5
```

### Ask (Interactive Chat)

Start an interactive chat session with your vault context:

```bash
mnemo --vault ~/my-vault ask --chat --provider ollama --model llama3
```

Or ask a single question:

```bash
mnemo --vault ~/my-vault ask \
    --query "Summarize our design decisions" \
    --provider claude \
    --model claude-3-5-sonnet-20240620
```

### Diagnostics

Check your environment and connection to LLM providers:

```bash
mnemo --vault ~/my-vault doctor
```

## 📖 Core Concepts

### Memory Types

Mnemo-Vault supports different types of memories inspired by cognitive science:

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
Mnemo-Vault/
├── mnemo/              # Main package
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
│   └── cli.py          # CLI implementation
├── tests/              # Test suite
└── examples/           # Example usage
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Indhar01/Mnemo-Vault.git
   cd Mnemo-Vault
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

## 📚 Documentation

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

- **Issues**: [GitHub Issues](https://github.com/Indhar01/Mnemo-Vault/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Indhar01/Mnemo-Vault/discussions)

## 🚦 Status

This project is in active development. While the core functionality is stable, the API may change in minor versions until we reach v1.0.0.

---

Made with ❤️ for better LLM memory management