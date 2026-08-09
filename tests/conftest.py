"""Pytest configuration and fixtures for MemoGraph tests."""

import faulthandler
import sys
import tempfile
import threading
from collections.abc import Generator
from pathlib import Path

import pytest

from memograph import MemoryKernel, MemoryType

# --- Windows teardown-hang diagnostic -------------------------------------
# Some Windows CI runs report "N passed" then hang at interpreter teardown
# (a non-daemon thread stuck in join()) until the runner sends
# KeyboardInterrupt. Arm faulthandler to dump ALL thread stacks if the
# process is still alive after a grace period, so the offending thread is
# named in the CI log. Repeats so it fires even during shutdown. This is a
# diagnostic; remove once the culprit is fixed.
faulthandler.enable()
_HANG_DUMP_SECONDS = 480
try:
    faulthandler.dump_traceback_later(
        _HANG_DUMP_SECONDS, repeat=True, exit=False, file=sys.stderr
    )
except (RuntimeError, ValueError):  # pragma: no cover - platform quirks
    pass


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """After the session, list any non-daemon threads still alive.

    A lingering non-daemon thread is what blocks interpreter exit on Windows;
    printing the roster here points straight at the leaker.
    """
    alive = [
        t
        for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon and t.is_alive()
    ]
    if alive:
        print(
            "\n[conftest] non-daemon threads still alive at session finish "
            "(these block process exit):",
            file=sys.stderr,
        )
        for t in alive:
            print(
                f"  - name={t.name!r} ident={t.ident} class={type(t)}", file=sys.stderr
            )


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
        tags=["python", "programming"],
    )

    kernel.remember(
        title="Test Memory 2",
        content="This memory discusses graph algorithms like BFS and DFS.",
        memory_type=MemoryType.SEMANTIC,
        tags=["algorithms", "graphs"],
    )

    kernel.remember(
        title="Meeting Notes",
        content="We decided to use PostgreSQL for the database.",
        memory_type=MemoryType.EPISODIC,
        tags=["meeting", "database"],
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
