"""Tests for MemoryNode dataclass.

Validates serialization, deserialization, defaults, and edge cases.
"""

from datetime import datetime, timezone

import pytest

from memograph.core.enums import MemoryType
from memograph.core.node import MemoryNode


class TestMemoryNodeCreation:
    """Test MemoryNode instantiation."""

    def test_basic_creation(self):
        node = MemoryNode(id="test", title="Test", content="Content")
        assert node.id == "test"
        assert node.title == "Test"
        assert node.memory_type == MemoryType.SEMANTIC

    def test_defaults(self):
        node = MemoryNode(id="n", title="T", content="C")
        assert node.links == []
        assert node.backlinks == []
        assert node.tags == []
        assert node.salience == 1.0
        assert node.access_count == 0
        assert node.source_path is None
        assert node.embedding is None
        assert isinstance(node.created_at, datetime)

    def test_full_creation(self):
        now = datetime.now(timezone.utc)
        node = MemoryNode(
            id="full",
            title="Full Node",
            content="Full content",
            memory_type=MemoryType.EPISODIC,
            links=["a", "b"],
            backlinks=["c"],
            tags=["tag1"],
            salience=0.8,
            access_count=5,
            last_accessed=now,
            created_at=now,
            modified_at=now,
            source_path="/path/to/file.md",
            frontmatter={"key": "value"},
            embedding=[0.1, 0.2, 0.3],
        )
        assert node.memory_type == MemoryType.EPISODIC
        assert node.links == ["a", "b"]
        assert node.salience == 0.8
        assert node.embedding == [0.1, 0.2, 0.3]


class TestToDict:
    """Test MemoryNode.to_dict()."""

    def test_basic_to_dict(self):
        node = MemoryNode(id="test", title="Test", content="Content")
        d = node.to_dict()
        assert d["id"] == "test"
        assert d["title"] == "Test"
        assert d["memory_type"] == "semantic"
        assert "links" not in d
        assert "embedding" not in d

    def test_to_dict_with_graph(self):
        node = MemoryNode(
            id="test", title="T", content="C", links=["a"], backlinks=["b"]
        )
        d = node.to_dict(include_graph=True)
        assert d["links"] == ["a"]
        assert d["backlinks"] == ["b"]

    def test_to_dict_with_embedding(self):
        node = MemoryNode(id="test", title="T", content="C", embedding=[0.1, 0.2])
        d = node.to_dict(include_embedding=True)
        assert d["embedding"] == [0.1, 0.2]

    def test_to_dict_without_embedding_when_none(self):
        node = MemoryNode(id="test", title="T", content="C")
        d = node.to_dict(include_embedding=True)
        assert "embedding" not in d

    def test_to_dict_contains_timestamps(self):
        node = MemoryNode(id="test", title="T", content="C")
        d = node.to_dict()
        assert "created_at" in d
        assert "modified_at" in d
        assert "last_accessed" in d


class TestFromDict:
    """Test MemoryNode.from_dict()."""

    def test_basic_from_dict(self):
        data = {"id": "test", "title": "Test", "content": "Content"}
        node = MemoryNode.from_dict(data)
        assert node.id == "test"
        assert node.title == "Test"
        assert node.memory_type == MemoryType.SEMANTIC

    def test_from_dict_with_type(self):
        data = {
            "id": "test",
            "title": "T",
            "content": "C",
            "memory_type": "episodic",
        }
        node = MemoryNode.from_dict(data)
        assert node.memory_type == MemoryType.EPISODIC

    def test_from_dict_with_enum_type(self):
        data = {
            "id": "test",
            "title": "T",
            "content": "C",
            "memory_type": MemoryType.PROCEDURAL,
        }
        node = MemoryNode.from_dict(data)
        assert node.memory_type == MemoryType.PROCEDURAL

    def test_from_dict_missing_required(self):
        with pytest.raises(ValueError, match="Missing required field"):
            MemoryNode.from_dict({"id": "test", "title": "T"})

    def test_from_dict_invalid_type(self):
        with pytest.raises(TypeError, match="memory_type must be"):
            MemoryNode.from_dict(
                {"id": "t", "title": "T", "content": "C", "memory_type": 123}
            )

    def test_from_dict_with_iso_datetime(self):
        data = {
            "id": "test",
            "title": "T",
            "content": "C",
            "created_at": "2024-01-15T12:00:00+00:00",
        }
        node = MemoryNode.from_dict(data)
        assert node.created_at.year == 2024

    def test_roundtrip(self):
        """Test to_dict -> from_dict roundtrip."""
        original = MemoryNode(
            id="rt",
            title="Roundtrip",
            content="Test content",
            memory_type=MemoryType.FACT,
            tags=["a", "b"],
            salience=0.75,
        )
        data = original.to_dict(include_graph=True)
        restored = MemoryNode.from_dict(data)
        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.memory_type == original.memory_type
        assert restored.tags == original.tags
        assert restored.salience == original.salience
