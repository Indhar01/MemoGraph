"""Tests for enhanced graph with O(1) indexing.

This test suite validates:
- Node ID index for O(1) lookups
- Tag index for fast tag queries
- Memory type index for filtering
- Backlink index for reverse lookups
- Graph statistics tracking
- Index consistency and validation
"""

import pytest

from memograph.core.enums import MemoryType
from memograph.core.graph_enhanced import EnhancedVaultGraph
from memograph.core.node import MemoryNode


@pytest.fixture
def sample_nodes():
    """Create sample nodes for testing."""
    nodes = [
        MemoryNode(
            id="python-tips",
            title="Python Tips",
            content="Useful Python tips",
            tags=["python", "programming"],
            memory_type=MemoryType.SEMANTIC,
            links=["ml-basics"],
            salience=0.8,
        ),
        MemoryNode(
            id="ml-basics",
            title="ML Basics",
            content="Machine learning fundamentals",
            tags=["python", "ml", "ai"],
            memory_type=MemoryType.SEMANTIC,
            links=["python-tips"],
            salience=0.9,
        ),
        MemoryNode(
            id="meeting-notes",
            title="Meeting Notes",
            content="Notes from team meeting",
            tags=["work", "meeting"],
            memory_type=MemoryType.EPISODIC,
            links=[],
            salience=0.5,
        ),
    ]
    return nodes


class TestNodeIndex:
    """Test node ID index for O(1) lookups."""

    def test_add_and_get(self, sample_nodes):
        """Test adding nodes and retrieving by ID."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # O(1) lookup
        node = graph.get("python-tips")
        assert node is not None
        assert node.title == "Python Tips"

        # Non-existent node
        assert graph.get("nonexistent") is None

    def test_remove_node(self, sample_nodes):
        """Test node removal updates index."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # Remove node
        assert graph.remove_node("python-tips") is True
        assert graph.get("python-tips") is None

        # Try to remove again
        assert graph.remove_node("python-tips") is False

    def test_all_nodes(self, sample_nodes):
        """Test iterating over all nodes."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        all_nodes = list(graph.all_nodes())
        assert len(all_nodes) == 3
        assert all(isinstance(n, MemoryNode) for n in all_nodes)


class TestTagIndex:
    """Test tag index for fast tag queries."""

    def test_get_by_tag(self, sample_nodes):
        """Test retrieving nodes by tag."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # Get nodes with 'python' tag
        python_nodes = graph.get_by_tag("python")
        assert len(python_nodes) == 2
        assert all("python" in n.tags for n in python_nodes)

        # Get nodes with 'work' tag
        work_nodes = graph.get_by_tag("work")
        assert len(work_nodes) == 1
        assert work_nodes[0].id == "meeting-notes"

        # Non-existent tag
        assert graph.get_by_tag("nonexistent") == []

    def test_get_by_tags_any(self, sample_nodes):
        """Test retrieving nodes matching any tag."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # Nodes with 'python' OR 'work'
        nodes = graph.get_by_tags(["python", "work"], match_all=False)
        assert len(nodes) == 3  # All nodes have at least one tag

    def test_get_by_tags_all(self, sample_nodes):
        """Test retrieving nodes matching all tags."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # Nodes with 'python' AND 'ml'
        nodes = graph.get_by_tags(["python", "ml"], match_all=True)
        assert len(nodes) == 1
        assert nodes[0].id == "ml-basics"

        # No nodes have both 'python' and 'work'
        nodes = graph.get_by_tags(["python", "work"], match_all=True)
        assert len(nodes) == 0

    def test_get_all_tags(self, sample_nodes):
        """Test getting all unique tags."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        all_tags = graph.get_all_tags()
        assert set(all_tags) == {"python", "programming", "ml", "ai", "work", "meeting"}
        assert all_tags == sorted(all_tags)  # Should be sorted

    def test_get_tag_counts(self, sample_nodes):
        """Test getting tag usage counts."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        counts = graph.get_tag_counts()
        assert counts["python"] == 2
        assert counts["ml"] == 1
        assert counts["work"] == 1

    def test_tag_index_update_on_remove(self, sample_nodes):
        """Test tag index updates when node is removed."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # Remove node with 'python' tag
        graph.remove_node("python-tips")

        # Should still have one node with 'python'
        python_nodes = graph.get_by_tag("python")
        assert len(python_nodes) == 1
        assert python_nodes[0].id == "ml-basics"

        # 'programming' tag should be gone
        assert graph.get_by_tag("programming") == []


class TestTypeIndex:
    """Test memory type index for filtering."""

    def test_get_by_type(self, sample_nodes):
        """Test retrieving nodes by memory type."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # Get semantic memories
        semantic = graph.get_by_type(MemoryType.SEMANTIC)
        assert len(semantic) == 2
        assert all(n.memory_type == MemoryType.SEMANTIC for n in semantic)

        # Get episodic memories
        episodic = graph.get_by_type(MemoryType.EPISODIC)
        assert len(episodic) == 1
        assert episodic[0].id == "meeting-notes"

        # No procedural memories
        procedural = graph.get_by_type(MemoryType.PROCEDURAL)
        assert len(procedural) == 0

    def test_get_type_counts(self, sample_nodes):
        """Test getting memory type counts."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        counts = graph.get_type_counts()
        assert counts["semantic"] == 2
        assert counts["episodic"] == 1


class TestBacklinkIndex:
    """Test backlink index for reverse lookups."""

    def test_get_backlinks(self, sample_nodes):
        """Test retrieving backlinks."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # python-tips links to ml-basics
        # ml-basics links to python-tips

        # Get backlinks to python-tips
        backlinks = graph.get_backlinks("python-tips")
        assert len(backlinks) == 1
        assert backlinks[0].id == "ml-basics"

        # Get backlinks to ml-basics
        backlinks = graph.get_backlinks("ml-basics")
        assert len(backlinks) == 1
        assert backlinks[0].id == "python-tips"

        # No backlinks to meeting-notes
        backlinks = graph.get_backlinks("meeting-notes")
        assert len(backlinks) == 0

    def test_backlink_index_update_on_remove(self, sample_nodes):
        """Test backlink index updates when node is removed."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # Remove python-tips (which links to ml-basics)
        graph.remove_node("python-tips")

        # ml-basics should have no backlinks now
        backlinks = graph.get_backlinks("ml-basics")
        assert len(backlinks) == 0


class TestNeighbors:
    """Test neighbor traversal with indexes."""

    def test_neighbors_depth_1(self, sample_nodes):
        """Test getting immediate neighbors."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # python-tips neighbors (depth 1)
        neighbors = graph.neighbors("python-tips", depth=1)
        assert len(neighbors) == 1
        assert neighbors[0].id == "ml-basics"

    def test_neighbors_depth_2(self, sample_nodes):
        """Test getting neighbors at depth 2."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # python-tips -> ml-basics -> python-tips (circular)
        neighbors = graph.neighbors("python-tips", depth=2)
        assert len(neighbors) == 1  # Only ml-basics (python-tips excluded)

    def test_neighbors_with_backlinks(self, sample_nodes):
        """Test neighbors including backlinks."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        neighbors = graph.neighbors("python-tips", depth=1, include_backlinks=True)
        assert len(neighbors) == 1
        assert neighbors[0].id == "ml-basics"

    def test_neighbors_without_backlinks(self, sample_nodes):
        """Test neighbors excluding backlinks."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # ml-basics has forward link to python-tips
        neighbors = graph.neighbors("ml-basics", depth=1, include_backlinks=False)
        assert len(neighbors) == 1
        assert neighbors[0].id == "python-tips"


class TestGraphStats:
    """Test graph statistics tracking."""

    def test_stats_after_add(self, sample_nodes):
        """Test statistics after adding nodes."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        stats = graph.get_stats()
        assert stats.total_nodes == 3
        assert stats.total_edges == 2  # python-tips <-> ml-basics
        assert stats.total_tags == 6  # Unique tags
        assert stats.nodes_by_type["semantic"] == 2
        assert stats.nodes_by_type["episodic"] == 1
        assert stats.isolated_nodes == 1  # meeting-notes

    def test_stats_after_remove(self, sample_nodes):
        """Test statistics after removing nodes."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        graph.remove_node("python-tips")

        stats = graph.get_stats()
        assert stats.total_nodes == 2
        assert stats.total_edges == 1  # Only ml-basics -> python-tips (broken)

    def test_degree_statistics(self, sample_nodes):
        """Test degree statistics."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        stats = graph.get_stats()
        assert stats.avg_degree > 0
        assert (
            stats.max_degree >= 2
        )  # python-tips and ml-basics have 2 connections each


class TestIndexMaintenance:
    """Test index consistency and maintenance."""

    def test_rebuild_indexes(self, sample_nodes):
        """Test rebuilding indexes from scratch."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # Manually corrupt an index
        graph._tag_index.clear()

        # Rebuild
        graph.rebuild_indexes()

        # Should be fixed
        python_nodes = graph.get_by_tag("python")
        assert len(python_nodes) == 2

    def test_validate_indexes(self, sample_nodes):
        """Test index validation."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        # All indexes should be valid
        results = graph.validate_indexes()
        assert all(results.values())

        # Corrupt tag index
        graph._tag_index["fake_tag"].add("fake_id")

        # Validation should fail
        results = graph.validate_indexes()
        assert not results["tag_index"]

    def test_clear(self, sample_nodes):
        """Test clearing graph and indexes."""
        graph = EnhancedVaultGraph()

        for node in sample_nodes:
            graph.add_node(node)

        graph.clear()

        # Everything should be empty
        assert len(graph._nodes) == 0
        assert len(graph._tag_index) == 0
        assert len(graph._type_index) == 0
        assert len(graph._backlink_index) == 0
        assert graph.get_stats().total_nodes == 0


class TestPerformance:
    """Test performance improvements from indexing."""

    def test_lookup_performance(self):
        """Test that indexed lookups are O(1)."""
        import time

        graph = EnhancedVaultGraph()

        # Add many nodes
        for i in range(1000):
            node = MemoryNode(
                id=f"node-{i}",
                title=f"Node {i}",
                content=f"Content {i}",
                tags=[f"tag-{i % 10}"],
                memory_type=MemoryType.SEMANTIC,
                salience=0.5,
            )
            graph.add_node(node)

        # Lookup should be fast (O(1))
        start = time.time()
        for _ in range(100):
            graph.get("node-500")
        lookup_time = time.time() - start

        # Should be very fast (< 0.01s for 100 lookups)
        assert lookup_time < 0.01

    def test_tag_query_performance(self):
        """Test that tag queries are O(1)."""
        import time

        graph = EnhancedVaultGraph()

        # Add many nodes with shared tags
        for i in range(1000):
            node = MemoryNode(
                id=f"node-{i}",
                title=f"Node {i}",
                content=f"Content {i}",
                tags=["common-tag"] if i % 2 == 0 else ["other-tag"],
                memory_type=MemoryType.SEMANTIC,
                salience=0.5,
            )
            graph.add_node(node)

        # Tag query should be fast (O(1))
        start = time.time()
        for _ in range(100):
            graph.get_by_tag("common-tag")
        query_time = time.time() - start

        # Should be very fast (< 0.05s for 100 queries, relaxed for test environment)
        assert query_time < 0.05
