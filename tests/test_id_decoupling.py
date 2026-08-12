"""Tests for ID / path decoupling (Step 1 of the self-organizing hierarchy).

Identity lives in frontmatter ``id`` and is independent of the file's path,
so a note can be moved into a folder hierarchy without breaking inbound
[[wikilinks]]. See docs/ADR_SELF_ORGANIZING_HIERARCHY.md.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from memograph.core.kernel import MemoryKernel
from memograph.core.parser import parse_file


class TestParserIdDecoupling:
    def test_frontmatter_id_preferred_over_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "topics" / "python"
            sub.mkdir(parents=True)
            md = sub / "async-stuff.md"
            md.write_text(
                "---\nid: python-async\ntitle: Async\n---\n\nBody\n",
                encoding="utf-8",
            )
            node = parse_file(md, root)
            # id comes from frontmatter, NOT from the topics/python/... path
            assert node.id == "python-async"

    def test_falls_back_to_stem_not_full_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "notes" / "deep"
            sub.mkdir(parents=True)
            md = sub / "My Note.md"
            md.write_text("---\ntitle: My Note\n---\n\nBody\n", encoding="utf-8")
            node = parse_file(md, root)
            # Stem-based fallback, folder prefix must NOT leak into the id
            assert node.id == "my-note"

    def test_id_stable_across_simulated_move(self):
        """Moving the file to a subfolder must not change its id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flat = root / "concurrency.md"
            flat.write_text(
                "---\nid: concurrency\ntitle: Concurrency\n---\n\nBody\n",
                encoding="utf-8",
            )
            id_before = parse_file(flat, root).id

            moved_dir = root / "topics" / "systems"
            moved_dir.mkdir(parents=True)
            moved = moved_dir / "concurrency.md"
            moved.write_text(flat.read_text(encoding="utf-8"), encoding="utf-8")
            flat.unlink()
            id_after = parse_file(moved, root).id

            assert id_before == id_after == "concurrency"


class TestBackfillIds:
    def test_backfill_adds_id_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "legacy.md").write_text(
                "---\ntitle: Legacy\n---\n\nBody\n", encoding="utf-8"
            )
            kernel = MemoryKernel(vault_path=str(root))
            result = kernel.backfill_ids()
            assert result["updated"] == 1
            text = (root / "legacy.md").read_text(encoding="utf-8")
            assert "id: legacy" in text
            # Still parses and keeps its title
            node = parse_file(root / "legacy.md", root)
            assert node.id == "legacy"
            assert node.title == "Legacy"

    def test_backfill_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.md").write_text(
                "---\nid: note\ntitle: Note\n---\n\nBody\n", encoding="utf-8"
            )
            kernel = MemoryKernel(vault_path=str(root))
            first = kernel.backfill_ids()
            assert first["updated"] == 0
            assert first["skipped"] == 1
            second = kernel.backfill_ids()
            assert second["updated"] == 0

    def test_backfill_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "legacy.md"
            p.write_text("---\ntitle: Legacy\n---\n\nBody\n", encoding="utf-8")
            before = p.read_text(encoding="utf-8")
            kernel = MemoryKernel(vault_path=str(root))
            result = kernel.backfill_ids(dry_run=True)
            assert result["updated"] == 1
            assert p.read_text(encoding="utf-8") == before  # unchanged

    def test_backfill_handles_no_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "plain.md"
            p.write_text("Just body text, no frontmatter.\n", encoding="utf-8")
            kernel = MemoryKernel(vault_path=str(root))
            kernel.backfill_ids()
            text = p.read_text(encoding="utf-8")
            assert text.startswith("---\nid: plain\n---")
            node = parse_file(p, root)
            assert node.id == "plain"


class TestIndexerDeleteByReverseMap:
    def test_deleted_file_with_custom_id_is_removed(self):
        """A note whose id != stem, in a subfolder, must be removed from the
        graph on deletion — resolved via rel_path -> id, not the stem."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "topics"
            sub.mkdir()
            md = sub / "filename-differs.md"
            md.write_text(
                "---\nid: custom-identity\ntitle: T\n---\n\nBody\n",
                encoding="utf-8",
            )
            kernel = MemoryKernel(vault_path=str(root))
            kernel.ingest(force=True)
            assert kernel.graph.get("custom-identity") is not None

            # Delete the file and re-ingest incrementally (cache path).
            md.unlink()
            kernel.ingest()
            assert kernel.graph.get("custom-identity") is None
