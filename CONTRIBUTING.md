# Contributing to Mnemo-Vault

Thank you for your interest in contributing to Mnemo-Vault! This guide will help you get started with developing and contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Commit Message Guidelines](#commit-message-guidelines)

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code.

## Getting Started

### Prerequisites

- Python 3.10 or higher
- pip or uv (recommended)
- git
- Ollama (for local testing) or API keys for Claude/OpenAI

### Development Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/Mnemo-Vault.git
   cd Mnemo-Vault
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install in development mode:**
   ```bash
   pip install -e ".[openai,anthropic]"
   pip install -e ".[dev]"  # Install development dependencies
   ```

4. **Install pre-commit hooks:**
   ```bash
   pre-commit install
   ```

### Verify Installation

```bash
# Run tests
pytest

# Run linter
ruff check .

# Format code
ruff format .
```

## Project Structure

```
Mnemo-Vault/
├── mnemo/              # Main package
│   ├── core/           # Core functionality (kernel, graph, retriever, etc.)
│   ├── adapters/       # Adapters for LLMs and embeddings
│   ├── storage/        # Storage and caching
│   └── cli.py          # CLI implementation
├── tests/              # Test suite
├── docs/               # Documentation
├── examples/           # Example usage
└── pyproject.toml      # Project configuration
```

## Coding Standards

### Style Guide

- Follow [PEP 8](https://peps.python.org/pep-0008/)
- Use [ruff](https://github.com/astral-sh/ruff) for linting and formatting
- Maximum line length: 100 characters
- Use type hints for all functions

### Type Annotations

Type hints are required for all public functions:

```python
def context_window(
    self,
    query: str,
    tags: List[str] | None = None,
    depth: int = 2,
    top_k: int = 8,
    token_limit: int = 2048,
) -> str:
    """Retrieves relevant context from the memory vault."""
    ...
```

### Docstrings

Use Google-style docstrings:

```python
def retrieve_nodes(
    self,
    query: str,
    tags: List[str] | None = None,
    depth: int = 2,
    top_k: int = 8,
) -> list[MemoryNode]:
    """Retrieve relevant memory nodes for a query.
    
    Args:
        query: Natural language query string
        tags: Optional list of tags to filter memories
        depth: Maximum graph traversal depth (default: 2)
        top_k: Maximum number of memories to retrieve (default: 8)
    
    Returns:
        List of relevant MemoryNode objects
    
    Example:
        >>> kernel = MemoryKernel("~/vault")
        >>> nodes = kernel.retrieve_nodes(
        ...     query="What is BFS?",
        ...     tags=["algorithms"],
        ...     depth=2
        ... )
    """
    ...
```

### Code Quality Tools

```bash
# Format code
ruff format .

# Lint code
ruff check .

# Fix auto-fixable issues
ruff check --fix .

# Type check
mypy mnemo/

# Run all pre-commit hooks
pre-commit run --all-files
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=mnemo --cov-report=html

# Run specific test file
pytest tests/test_kernel.py

# Run tests matching a pattern
pytest -k "test_remember"

# Run with verbose output
pytest -v
```

### Writing Tests

- Place tests in the `tests/` directory
- Name test files as `test_*.py`
- Use descriptive test names: `test_<functionality>_<expected_behavior>`
- Use pytest fixtures for common setup
- Aim for high test coverage (>80%)

Example:

```python
def test_context_window_respects_token_limit():
    """Test that context window doesn't exceed token limit."""
    with tempfile.TemporaryDirectory() as tmp:
        kernel = MemoryKernel(tmp)
        kernel.remember("Title", "content" * 1000)
        
        context = kernel.context_window(
            query="test",
            token_limit=100
        )
        
        # Rough estimation: 100 tokens ≈ 380 characters
        assert len(context) < 500
```

### Test Categories

Use pytest markers to categorize tests:

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

## Pull Request Process

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes:**
   - Write clean, documented code
   - Add tests for new functionality
   - Update documentation as needed

3. **Run quality checks:**
   ```bash
   pre-commit run --all-files
   pytest
   ```

4. **Commit your changes:**
   ```bash
   git add .
   git commit -m "feat: add new feature"
   ```

5. **Push to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Create a Pull Request:**
   - Go to the original repository on GitHub
   - Click "New Pull Request"
   - Select your fork and branch
   - Fill out the PR template
   - Link any related issues

### Pull Request Guidelines

- Keep PRs focused on a single feature or fix
- Write clear PR descriptions explaining:
  - What changes were made
  - Why the changes were necessary
  - How to test the changes
- Ensure all tests pass
- Update documentation if needed
- Respond to review comments promptly

## Commit Message Guidelines

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>: <subject>

<body>

<footer>
```

### Types

- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation changes
- **test**: Adding or updating tests
- **refactor**: Code refactoring
- **perf**: Performance improvements
- **chore**: Maintenance tasks
- **ci**: CI/CD changes

### Examples

```bash
feat: add embedding persistence

Embeddings are now cached to disk to avoid redundant computation.
Speeds up subsequent queries by 10x for large vaults.

Closes #45

---

fix: handle malformed YAML frontmatter

Parser now gracefully handles corrupt frontmatter instead of crashing.
Invalid frontmatter is logged as a warning and skipped.

---

docs: add graph traversal examples

Added examples demonstrating BFS traversal with different depths.
```

## Development Tips

### Debugging

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Print the internal graph structure
print(kernel.graph._nodes)
print(kernel.graph._adjacency)

# Inspect retrieved nodes
nodes = kernel.retrieve_nodes(query="test")
for node in nodes:
    print(f"{node.title}: salience={node.salience}, tags={node.tags}")
```

### Common Issues

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError` | Run `pip install -e ".[openai,anthropic]"` |
| Pre-commit hooks fail | Run `pre-commit run --all-files` to see issues |
| Tests fail with Ollama | Ensure Ollama is running: `ollama serve` |
| Type errors in editor | Install mypy language server extension |

## Getting Help

- Check [existing issues](https://github.com/Indhar01/Mnemo-Vault/issues)
- Read the [README](README.md) and documentation
- Open a new issue with detailed information

## Recognition

Contributors will be recognized in:
- The project's README
- Release notes
- The CHANGELOG

Thank you for contributing to Mnemo-Vault! 🎉
