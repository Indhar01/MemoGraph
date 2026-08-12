"""Tests for the self-organizing hierarchy (Steps 2 & 3).

- HierarchyResolver: pure path resolution (flat / by_type).
- remember(): files new notes per the strategy while keeping ``id`` = slug so
  wikilinks and graph resolution survive. See docs/ADR_SELF_ORGANIZING_HIERARCHY.md.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from memograph.core.enums import MemoryType
from memograph.core.hierarchy import HierarchyResolver
from memograph.core.kernel import MemoryKernel


class TestHierarchyResolver:
    def test_flat_default(self):
        r = HierarchyResolver()
        assert r.strategy_name == "flat"
        assert r.relative_path_for("x", MemoryType.FACT) == "x.md"

    def test_by_type(self):
        r = HierarchyResolver("by_type")
        assert (
            r.relative_path_for("py-async", MemoryType.SEMANTIC)
            == "semantic/py-async.md"
        )
        assert r.relative_path_for("sync", MemoryType.EPISODIC) == "episodic/sync.md"
        assert r.relative_path_for("cfg", MemoryType.PROCEDURAL) == "procedural/cfg.md"

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError):
            HierarchyResolver("by_moon_phase")

    def test_empty_slug_raises(self):
        with pytest.raises(ValueError):
            HierarchyResolver("flat").relative_path_for("", MemoryType.FACT)

    def test_always_returns_md_relative_posix(self):
        r = HierarchyResolver("by_type")
        rel = r.relative_path_for("note", MemoryType.SEMANTIC)
        assert rel.endswith(".md")
        assert not rel.startswith("/")
        assert "\\" not in rel

    def test_custom_resolver_takes_precedence(self):
        def custom(slug, mtype, tags):
            return f"custom/{slug}.md"

        r = HierarchyResolver("ignored", custom=custom)
        assert r.relative_path_for("x", MemoryType.FACT) == "custom/x.md"

    def test_custom_unsafe_path_rejected(self):
        def bad(slug, mtype, tags):
            return "../escape.md"

        r = HierarchyResolver("x", custom=bad)
        with pytest.raises(ValueError):
            r.relative_path_for("x", MemoryType.FACT)


class TestRememberFiling:
    def test_flat_writes_to_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            k = MemoryKernel(vault_path=tmp)  # default flat
            path = k.remember(
                title="Python Async", content="tips", memory_type=MemoryType.SEMANTIC
            )
            assert Path(path).relative_to(tmp).as_posix() == "python-async.md"

    def test_by_type_files_into_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            k = MemoryKernel(vault_path=tmp, hierarchy_strategy="by_type")
            p_sem = k.remember(
                title="Design Note", content="c", memory_type=MemoryType.SEMANTIC
            )
            p_epi = k.remember(
                title="Standup", content="c", memory_type=MemoryType.EPISODIC
            )
            assert Path(p_sem).relative_to(tmp).as_posix() == "semantic/design-note.md"
            assert Path(p_epi).relative_to(tmp).as_posix() == "episodic/standup.md"

    def test_id_is_slug_not_path(self):
        """A note filed in a subfolder must keep id == slug so wikilinks work."""
        with tempfile.TemporaryDirectory() as tmp:
            k = MemoryKernel(vault_path=tmp, hierarchy_strategy="by_type")
            k.remember(title="Event Loop", content="c", memory_type=MemoryType.SEMANTIC)
            k.ingest(force=True)
            assert k.graph.get("event-loop") is not None
            # id must NOT include the folder prefix
            assert k.graph.get("semantic/event-loop") is None

    def test_wikilink_resolves_across_folders(self):
        """A note in one type-folder linking to a note in another must connect."""
        with tempfile.TemporaryDirectory() as tmp:
            k = MemoryKernel(vault_path=tmp, hierarchy_strategy="by_type")
            k.remember(
                title="Event Loop",
                content="the core of async",
                memory_type=MemoryType.SEMANTIC,
            )
            k.remember(
                title="Async Meeting",
                content="we discussed [[event-loop]] today",
                memory_type=MemoryType.EPISODIC,
            )
            k.ingest(force=True)
            src = k.graph.get("async-meeting")
            assert src is not None
            assert "event-loop" in src.links  # edge survives the folder split

    def test_collision_handled_within_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            k = MemoryKernel(vault_path=tmp, hierarchy_strategy="by_type")
            p1 = k.remember(title="Note", content="a", memory_type=MemoryType.FACT)
            p2 = k.remember(title="Note", content="b", memory_type=MemoryType.FACT)
            assert Path(p1).relative_to(tmp).as_posix() == "fact/note.md"
            assert Path(p2).relative_to(tmp).as_posix() == "fact/note-2.md"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("MEMOGRAPH_HIERARCHY_STRATEGY", "by_type")
        with tempfile.TemporaryDirectory() as tmp:
            k = MemoryKernel(vault_path=tmp)
            assert k.hierarchy.strategy_name == "by_type"

    def test_invalid_env_falls_back_to_flat(self, monkeypatch):
        monkeypatch.setenv("MEMOGRAPH_HIERARCHY_STRATEGY", "nonsense")
        with tempfile.TemporaryDirectory() as tmp:
            k = MemoryKernel(vault_path=tmp)
            assert k.hierarchy.strategy_name == "flat"

    def test_retrieval_works_on_hierarchical_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            k = MemoryKernel(vault_path=tmp, hierarchy_strategy="by_type")
            k.remember(
                title="Python Async",
                content="async await coroutines event loop",
                memory_type=MemoryType.SEMANTIC,
            )
            k.remember(
                title="Bread", content="sourdough baking", memory_type=MemoryType.FACT
            )
            k.ingest(force=True)
            results = k.retrieve_nodes(
                query="async coroutines", top_k=2, use_cache=False
            )
            assert results
            assert results[0].id == "python-async"
