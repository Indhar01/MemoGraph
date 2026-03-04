# Installation Guide

This guide covers different ways to install MemoGraph and its dependencies.

## Requirements

- Python 3.10 or higher
- pip (Python package manager)

## Basic Installation

Install the core package from PyPI:

```bash
pip install memograph
```

This installs the basic functionality including:
- Core memory kernel
- Graph-based retrieval
- Markdown parsing
- CLI tool

## Optional Dependencies

### For OpenAI Integration

If you want to use OpenAI's GPT models or embeddings:

```bash
pip install memograph[openai]
```

This includes:
- `openai` - OpenAI API client
- `tiktoken` - Token counting for OpenAI models

### For Anthropic Claude

To use Claude models:

```bash
pip install memograph[anthropic]
```

### For Ollama

For local LLM support with Ollama:

```bash
pip install memograph[ollama]
```

### For Embedding Support

To enable semantic search with embeddings:

```bash
pip install memograph[embeddings]
```

This includes:
- `sentence-transformers` - For generating embeddings
- `numpy` - For vector operations

### Install Everything

To install all optional dependencies:

```bash
pip install memograph[all]
```

## Development Installation

For contributors and developers:

1. Clone the repository:
   ```bash
   git clone https://github.com/Indhar01/MemoGraph.git
   cd MemoGraph
   ```

2. Create a virtual environment (recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install in editable mode with dev dependencies:
   ```bash
   pip install -e ".[all,dev]"
   ```

4. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```

## Verify Installation

Check that everything is installed correctly:

```bash
memograph --version
```

Or in Python:

```python
import memograph
print(memograph.__version__)
```

## Troubleshooting

### ImportError: No module named 'memograph'

Make sure you've installed the package:
```bash
pip install memograph
```

### Command 'memograph' not found

The CLI might not be in your PATH. Try:
```bash
python -m memograph --version
```

### Permission Errors

On Linux/Mac, you might need to use `--user`:
```bash
pip install --user memograph
```

Or use a virtual environment (recommended).

### Dependency Conflicts

If you encounter dependency conflicts, try creating a fresh virtual environment:
```bash
python -m venv fresh_env
source fresh_env/bin/activate  # Windows: fresh_env\Scripts\activate
pip install memograph[all]
```

## Next Steps

- Read the [Quick Start Guide](../README.md#-quick-start)
- Check out [examples](../examples/)
- Read the [Architecture Documentation](ARCHITECTURE.md)