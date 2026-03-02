# Quick Start Guide for Developers

This guide will get you up and running with Mnemo-Vault development in 5 minutes.

## Prerequisites

- Python 3.10 or higher
- Git
- pip or uv

## Setup (5 minutes)

### 1. Clone and Install (2 min)

```bash
# Clone the repository
git clone https://github.com/Indhar01/Mnemo-Vault.git
cd Mnemo-Vault

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode with all dependencies
pip install -e ".[all,dev]"
```

### 2. Install Pre-commit Hooks (30 sec)

```bash
pre-commit install
```

This ensures code quality checks run automatically before each commit.

### 3. Verify Installation (1 min)

```bash
# Run tests
pytest

# Check formatting
ruff check .

# Type check
mypy mnemo/
```

### 4. Try the Examples (1 min)

```bash
# Run basic example
python examples/basic_usage.py

# Try CLI (set up a test vault first)
mnemo --vault ~/test-vault doctor
```

## Quick Development Workflow

### Make a Change

```bash
# Create a feature branch
git checkout -b feature/my-feature

# Edit code
# mnemo/core/kernel.py

# Add tests
# tests/test_my_feature.py

# Run tests
pytest tests/test_my_feature.py -v

# Check your changes
ruff check .
```

### Commit Your Changes

```bash
# Add files
git add .

# Commit (pre-commit hooks run automatically)
git commit -m "feat: add new feature"

# If hooks fail, fix issues and try again
git add .
git commit -m "feat: add new feature"
```

### Push and Create PR

```bash
# Push to your fork
git push origin feature/my-feature

# Go to GitHub and create a Pull Request
```

## Common Commands

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=mnemo

# Run specific test
pytest tests/test_kernel.py::test_remember

# Run slow tests
pytest -m slow

# Skip slow tests
pytest -m "not slow"

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

## Project Structure Quick Reference

```
mnemo/
├── core/           # Core functionality
│   ├── kernel.py   # Main API (MemoryKernel)
│   ├── graph.py    # Graph structure
│   ├── retriever.py # Hybrid retrieval
│   ├── indexer.py  # File indexing
│   └── parser.py   # Markdown parsing
├── adapters/       # External integrations
│   ├── embeddings/ # Embedding providers
│   ├── frameworks/ # LangChain, LlamaIndex
│   └── llm/        # LLM providers
└── storage/        # Caching and storage
```

## Next Steps

1. **Read the docs**: Check out [ARCHITECTURE.md](ARCHITECTURE.md) for technical details
2. **Run examples**: Try all examples in `examples/` directory
3. **Add a feature**: See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines
4. **Join discussions**: Open an issue or start a discussion on GitHub

## Need Help?

- 📖 Read [CONTRIBUTING.md](../CONTRIBUTING.md)
- 🏗️ Check [ARCHITECTURE.md](ARCHITECTURE.md)
- 🐛 Open an [issue](https://github.com/Indhar01/Mnemo-Vault/issues)
- 💬 Start a [discussion](https://github.com/Indhar01/Mnemo-Vault/discussions)

Happy coding! 🚀
