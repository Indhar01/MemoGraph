"""Tests for VaultGraph.find_path and index-based lookups."""

from memograph.core.enums import MemoryType
from memograph.core.graph import GraphStats, VaultGraph
from memograph.core.node import MemoryNode


def make_node(id, title=None, links=None, tags=None, memory_type=MemoryType.SEMANTIC):
    return MemoryNode(
        id=id,
        title=title or id,
        content=f"Content for {id}",
        memory_type=memory_type,
        links=links or [],
        tags=tags or [],
    )


class TestFindPath:
    """Test find_path BFS shortest path."""

    def test_direct_link(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", links=["b"]))
        graph.add_node(make_node("b"))
        path = graph.find_path("a", "b")
        assert path is not None
        assert len(path) == 2
        assert path[0].id == "a"
        assert path[1].id == "b"

    def test_two_hop(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", links=["b"]))
        graph.add_node(make_node("b", links=["c"]))
        graph.add_node(make_node("c"))
        path = graph.find_path("a", "c")
        assert path is not None
        assert len(path) == 3

    def test_no_path(self):
        graph = VaultGraph()
        graph.add_node(make_node("a"))
        graph.add_node(make_node("b"))
        path = graph.find_path("a", "b")
        assert path is None

    def test_same_node(self):
        graph = VaultGraph()
        graph.add_node(make_node("a"))
        path = graph.find_path("a", "a")
        assert path is not None
        assert len(path) == 1

    def test_via_backlinks(self):
        graph = VaultGraph()
        graph.add_node(make_node("a"))
        graph.add_node(make_node("b", links=["a"]))
        # b -> a, so a <- b (backlink). Path from a to b uses backlink.
        path = graph.find_path("a", "b")
        assert path is not None
        assert len(path) == 2

    def test_nonexistent_node(self):
        graph = VaultGraph()
        graph.add_node(make_node("a"))
        assert graph.find_path("a", "z") is None
        assert graph.find_path("z", "a") is None


class TestGraphIndexLookups:
    """Test tag/type index lookups."""

    def test_get_by_tag(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", tags=["python", "tips"]))
        graph.add_node(make_node("b", tags=["docker"]))
        result = graph.get_by_tag("python")
        assert len(result) == 1
        assert result[0].id == "a"

    def test_get_by_tags_any(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", tags=["python"]))
        graph.add_node(make_node("b", tags=["docker"]))
        graph.add_node(make_node("c", tags=["python", "docker"]))
        result = graph.get_by_tags(["python", "docker"])
        assert len(result) == 3

    def test_get_by_tags_all(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", tags=["python"]))
        graph.add_node(make_node("b", tags=["python", "docker"]))
        result = graph.get_by_tags(["python", "docker"], match_all=True)
        assert len(result) == 1
        assert result[0].id == "b"

    def test_get_by_type(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", memory_type=MemoryType.EPISODIC))
        graph.add_node(make_node("b", memory_type=MemoryType.SEMANTIC))
        result = graph.get_by_type(MemoryType.EPISODIC)
        assert len(result) == 1

    def test_get_all_tags(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", tags=["beta", "alpha"]))
        graph.add_node(make_node("b", tags=["gamma"]))
        tags = graph.get_all_tags()
        assert tags == ["alpha", "beta", "gamma"]

    def test_get_tag_counts(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", tags=["python"]))
        graph.add_node(make_node("b", tags=["python", "docker"]))
        counts = graph.get_tag_counts()
        assert counts["python"] == 2
        assert counts["docker"] == 1

    def test_get_type_counts(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", memory_type=MemoryType.EPISODIC))
        graph.add_node(make_node("b", memory_type=MemoryType.EPISODIC))
        graph.add_node(make_node("c", memory_type=MemoryType.FACT))
        counts = graph.get_type_counts()
        assert counts["episodic"] == 2
        assert counts["fact"] == 1


class TestGraphStats:
    """Test GraphStats tracking."""

    def test_stats_after_add(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", tags=["t1"], links=["b"]))
        graph.add_node(make_node("b", tags=["t1", "t2"]))
        stats = graph.get_stats()
        assert stats.total_nodes == 2
        assert stats.total_tags == 2
        assert stats.total_edges == 1

    def test_stats_to_dict(self):
        stats = GraphStats(total_nodes=5, total_edges=3)
        d = stats.to_dict()
        assert d["total_nodes"] == 5
        assert d["total_edges"] == 3

    def test_rebuild_indexes(self):
        graph = VaultGraph()
        graph.add_node(make_node("a", tags=["x"]))
        graph.add_node(make_node("b", tags=["y"]))
        graph.rebuild_indexes()
        assert len(graph.get_by_tag("x")) == 1
        assert len(graph.get_by_tag("y")) == 1

    def test_validate_indexes(self):
        graph = VaultGraph()
        graph.add_node(
            make_node("a", tags=["t"], memory_type=MemoryType.FACT, links=["b"])
        )
        graph.add_node(make_node("b"))
        result = graph.validate_indexes()
        assert all(result.values())
