"""Phase 2.2 concurrency audit: stress test the kernel under
parallel remember/search.

The bar is correctness, not throughput:

- No exceptions raised that aren't expected.
- No deadlocks (test must finish within the timeout).
- Final state matches the operation log: after concurrent creates,
  ``ingest()`` must surface every file written. (``remember()``
  writes a markdown file but does not touch ``self.graph`` — the
  graph is rebuilt by ``ingest()``.)

Marked ``stress`` so it's opt-in (slower than unit tests). Run with::

    pytest tests/stress/test_concurrent_kernel.py -m stress --no-cov
"""

from __future__ import annotations

import threading

import pytest

from memograph import MemoryKernel, MemoryType


pytestmark = pytest.mark.stress


@pytest.fixture
def kernel(tmp_path):
    return MemoryKernel(str(tmp_path / "vault"))


def _create_one(kernel: MemoryKernel, idx: int) -> str:
    """remember() returns a path string in this version; we just want to know
    creates succeed."""
    return kernel.remember(
        title=f"concurrent-{idx}",
        content=f"body {idx}",
        memory_type=MemoryType.SEMANTIC,
        tags=["stress"],
    )


def test_concurrent_creates_no_lost_writes(kernel):
    """N threads each create M memories; after a final ingest() every one
    must be visible in the graph (no thread silently overwrote another's file)."""
    workers = 8
    per_worker = 16

    successes = 0
    success_lock = threading.Lock()
    errors: list[BaseException] = []

    def run(start: int) -> None:
        nonlocal successes
        for i in range(start, start + per_worker):
            try:
                _create_one(kernel, i)
                with success_lock:
                    successes += 1
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(w * per_worker,)) for w in range(workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
        assert not t.is_alive(), "deadlock: thread did not finish"

    assert not errors, f"unexpected errors during concurrent creates: {errors[:3]}"
    assert successes == workers * per_worker

    # remember() writes a file; the graph is rebuilt by ingest(). Run it now
    # and assert every successful create surfaced — i.e. no two threads
    # collided on the same path or lost a write.
    stats = kernel.ingest()
    assert stats["indexed"] >= successes, (
        f"lost writes: ingested {stats['indexed']} files, "
        f"expected at least {successes}"
    )
    assert len(kernel.graph.all_nodes()) >= successes


def test_concurrent_create_search(kernel):
    """Searches must not crash while creates are landing."""
    n_creates = 64
    n_searches = 200

    errors: list[BaseException] = []

    def creator() -> None:
        for i in range(n_creates):
            try:
                _create_one(kernel, i)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    def searcher() -> None:
        try:
            for _ in range(n_searches):
                # Touch the read path; result correctness isn't asserted.
                kernel.search("body")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=creator),
        threading.Thread(target=searcher),
        threading.Thread(target=searcher),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
        assert not t.is_alive(), "deadlock: thread did not finish"

    assert not errors, f"unexpected errors: {errors[:3]}"
