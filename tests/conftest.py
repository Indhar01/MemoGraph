"""Pytest configuration and fixtures for Mnemo-Vault tests."""
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from mnemo import MemoryKernel, MemoryType


@pytest.fixture
def temp_vault() -> Generator[Path, None, None]:
    """Create a temporary vault directory for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def kernel(temp_vault: Path) -> MemoryKernel:
    """Create a MemoryKernel instance with a temporary vault."""
    return MemoryKernel(str(temp_vault))


@pytest.fixture
def populated_kernel(kernel: MemoryKernel) -> MemoryKernel:
    """Create a kernel with some test memories."""
    kernel.remember(
        title="Test Memory 1",
        content="This is a test memory about Python programming.",
        memory_type=MemoryType.SEMANTIC,
        tags=["python", "programming"]
    )
    
    kernel.remember(
        title="Test Memory 2",
        content="This memory discusses graph algorithms like BFS and DFS.",
        memory_type=MemoryType.SEMANTIC,
        tags=["algorithms", "graphs"]
    )
    
    kernel.remember(
        title="Meeting Notes",
        content="We decided to use PostgreSQL for the database.",
        memory_type=MemoryType.EPISODIC,
        tags=["meeting", "database"]
    )
    
    # Ingest the memories
    kernel.ingest()
    return kernel


@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment variables before each test."""
    import os
    
    # Store original environment
    original_env = os.environ.copy()
    
    yield
    
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)