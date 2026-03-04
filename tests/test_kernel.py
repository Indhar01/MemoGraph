import tempfile
import unittest
from pathlib import Path

from memograph import MemoryKernel, MemoryType


class KernelTests(unittest.TestCase):
    def test_remember_ingest_and_context_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = MemoryKernel(tmp)

            created = kernel.remember(
                title="Team Sync",
                content="Decided to use BFS graph traversal for retrieval.",
                memory_type=MemoryType.EPISODIC,
                tags=["#design", "retrieval"],
            )
            self.assertTrue(Path(created).exists())

            stats = kernel.ingest()
            self.assertEqual(stats["total"], 1)

            context = kernel.context_window(
                query="how does retrieval work",
                tags=["retrieval"],
                depth=2,
                top_k=4,
                token_limit=256,
            )
            self.assertIn("Team Sync", context)
            self.assertIn("BFS graph traversal", context)

    def test_remember_generates_unique_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = MemoryKernel(tmp)

            first = kernel.remember("Same Title", "one", tags=["a"])
            second = kernel.remember("Same Title", "two", tags=["b"])

            self.assertNotEqual(first, second)
            self.assertTrue(Path(first).exists())
            self.assertTrue(Path(second).exists())


if __name__ == "__main__":
    unittest.main()
