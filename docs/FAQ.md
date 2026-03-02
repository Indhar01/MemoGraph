# Frequently Asked Questions

## General Questions

### What is Mnemo-Vault?

Mnemo-Vault is a graph-based memory system for Large Language Models (LLMs). It helps LLMs maintain long-term memory by storing information in a knowledge graph and retrieving relevant context when needed.

### Why use Mnemo-Vault?

- **Long-term Memory**: LLMs have limited context windows. Mnemo-Vault provides unlimited memory storage.
- **Intelligent Retrieval**: Combines keyword search, graph traversal, and semantic embeddings for better context retrieval.
- **Human-Readable**: All memories are stored as markdown files, making them easy to read and edit.
- **Flexible Integration**: Works with multiple LLM providers and can be integrated into existing workflows.

### How is this different from vector databases?

Mnemo-Vault combines multiple retrieval strategies:
- **Keyword Matching**: Fast, deterministic search
- **Graph Traversal**: Follows relationships between concepts
- **Vector Embeddings** (optional): Semantic similarity search

This hybrid approach often outperforms pure vector search, especially for knowledge graphs with explicit relationships.

## Installation & Setup

### What Python version do I need?

Python 3.10 or higher is required.

### Can I use this without internet connection?

Yes! If you use Ollama for local LLM inference, Mnemo-Vault can run completely offline.

### Do I need to install all dependencies?

No. Install only what you need:
- Core functionality works without any LLM provider
- Add `[openai]`, `[anthropic]`, or `[ollama]` as needed
- Embeddings are optional (`[embeddings]`)

## Usage

### How do I structure my vault?

Store markdown files anywhere in your vault directory. Each file should have:

```markdown
---
title: "My Note"
memory_type: semantic
tags: [ai, ml]
salience: 0.7
---

Your content here with [[wikilinks]] to other notes.
```

### What are memory types?

- **Episodic**: Personal experiences, meeting notes, events
- **Semantic**: General knowledge, documentation, concepts
- **Procedural**: How-to guides, processes, tutorials
- **Fact**: Discrete facts, configuration values

### How does graph traversal work?

Mnemo-Vault uses BFS (Breadth-First Search) to explore your knowledge graph:

1. Start with nodes matching your query
2. Follow wikilinks to related notes
3. Traverse up to `depth` levels
4. Rank by relevance and salience

### What is salience scoring?

Salience (0.0 to 1.0) represents memory importance:
- **0.9-1.0**: Critical information
- **0.7-0.8**: Important concepts
- **0.5-0.6**: Normal information
- **0.3-0.4**: Minor details
- **0.0-0.2**: Low priority

### Can I use this with LangChain or LlamaIndex?

Yes! Mnemo-Vault provides adapters for both frameworks. See the `mnemo/adapters/frameworks/` directory for integration examples.

## Performance

### How fast is indexing?

Mnemo-Vault uses smart caching:
- First index: Processes all files
- Subsequent indexes: Only processes changed files
- Typical performance: 100-1000 files/second (depending on file size)

### Does it scale to large vaults?

Yes. The system is designed for:
- Thousands of markdown files
- Millions of tokens
- Deep graph structures

Graph traversal is optimized with BFS and early stopping.

### Do I need GPU for embeddings?

No, but it helps. Sentence-transformers can use CPU, but GPU significantly speeds up embedding generation.

## Troubleshooting

### My context window is too large

Adjust parameters:
```python
context = kernel.context_window(
    query="...",
    top_k=5,      # Reduce number of memories
    depth=1,      # Reduce graph depth
    token_limit=2000  # Set explicit token limit
)
```

### Indexing is slow

- Use `--force` flag sparingly (only when needed)
- Ensure files have proper YAML frontmatter
- Check for very large files that might need splitting

### Links aren't being detected

Mnemo-Vault supports:
- `[[WikiLinks]]`
- `[[Link|Display Text]]`
- Standard markdown links are also indexed

Ensure your wikilinks:
- Don't have spaces before/after brackets
- Match actual file titles or slugs

### Getting "No relevant memories found"

Try:
- Broaden your search query
- Remove restrictive tag filters
- Increase `top_k` parameter
- Check that files are properly indexed with `mnemo ingest`

## Integration

### Can I use this in production?

Mnemo-Vault is in alpha (v0.0.x). The core functionality is stable, but the API may change before v1.0.0. Use in production with appropriate testing.

### How do I back up my vault?

Your vault is just a directory of markdown files. Back it up like any other directory:
- Use git for version control
- Cloud sync (Dropbox, Google Drive, etc.)
- Regular file system backups
- Export to other formats as needed

### Can I sync my vault across devices?

Yes! Since vaults are just markdown files, use:
- Git for version control and syncing
- Cloud storage services
- Syncthing or similar tools
- Network file systems

## Community & Support

### How can I contribute?

See our [Contributing Guide](../CONTRIBUTING.md) for details on:
- Reporting bugs
- Suggesting features
- Contributing code
- Improving documentation

### Where can I get help?

- [GitHub Issues](https://github.com/Indhar01/Mnemo-Vault/issues) - Bug reports and feature requests
- [GitHub Discussions](https://github.com/Indhar01/Mnemo-Vault/discussions) - Questions and community chat
- [Documentation](../README.md) - Official docs and guides

### Is there a roadmap?

Check our [GitHub Issues](https://github.com/Indhar01/Mnemo-Vault/issues) and [Projects](https://github.com/Indhar01/Mnemo-Vault/projects) for planned features and development status.