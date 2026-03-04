import tempfile
import unittest
from pathlib import Path

from memograph.core.graph import VaultGraph
from memograph.core.indexer import VaultIndexer


class IndexerTests(unittest.TestCase):
    def test_second_index_skips_but_still_loads_graph_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.md").write_text("hello #tag", encoding="utf-8")

            indexer = VaultIndexer(root)

            first_graph = VaultGraph()
            indexed, skipped = indexer.index(first_graph)
            self.assertEqual(indexed, 1)
            self.assertEqual(skipped, 0)
            self.assertIsNotNone(first_graph.get("note"))

            second_graph = VaultGraph()
            indexed2, skipped2 = indexer.index(second_graph)
            self.assertEqual(indexed2, 0)
            self.assertEqual(skipped2, 1)
            self.assertIsNotNone(second_graph.get("note"))

    def test_force_reindex_marks_as_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "force.md").write_text("hello", encoding="utf-8")

            indexer = VaultIndexer(root)
            indexer.index(VaultGraph())
            indexed, skipped = indexer.index(VaultGraph(), force=True)

            self.assertEqual(indexed, 1)
            self.assertEqual(skipped, 0)


if __name__ == "__main__":
    unittest.main()
