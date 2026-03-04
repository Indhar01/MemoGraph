import tempfile
import unittest
from pathlib import Path

from memograph.core.enums import MemoryType
from memograph.core.parser import parse_file


class ParserTests(unittest.TestCase):
    def test_parse_frontmatter_with_bom_and_crlf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            md = root / "My Note.md"
            text = (
                "---\r\n"
                "title: Retrieval Notes\r\n"
                "memory_type: semantic\r\n"
                "salience: 0.8\r\n"
                "created: '2026-03-01T00:00:00'\r\n"
                "---\r\n\r\n"
                "Use [[Link Note]] in graph retrieval. #retrieval #design\r\n"
            )
            md.write_text(text, encoding="utf-8-sig")

            node = parse_file(md, root)

            self.assertEqual(node.id, "my-note")
            self.assertEqual(node.title, "Retrieval Notes")
            self.assertEqual(node.memory_type, MemoryType.SEMANTIC)
            self.assertAlmostEqual(node.salience, 0.8)
            self.assertIn("link-note", node.links)
            self.assertIn("retrieval", node.tags)
            self.assertIn("design", node.tags)
            self.assertFalse(node.content.startswith("---"))

    def test_invalid_memory_type_defaults_to_semantic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            md = root / "x.md"
            md.write_text(
                "---\nmemory_type: unknown\n---\n\nhello\n",
                encoding="utf-8",
            )

            node = parse_file(md, root)
            self.assertEqual(node.memory_type, MemoryType.SEMANTIC)


if __name__ == "__main__":
    unittest.main()
