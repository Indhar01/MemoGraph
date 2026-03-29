# core/graph.py
import logging
from collections import defaultdict
from dataclasses import dataclass

from .entity import EntityNode, ExtractionResult
from .enums import MemoryType
from .node import MemoryNode

logger = logging.getLogger("memograph.graph")


@dataclass
class GraphStats:
    """Statistics for graph structure and performance."""

    total_nodes: int = 0
    total_edges: int = 0
    total_tags: int = 0
    nodes_by_type: dict[str, int] | None = None
    avg_degree: float = 0.0
    max_degree: int = 0
    isolated_nodes: int = 0

    def __post_init__(self):
        if self.nodes_by_type is None:
            self.nodes_by_type: dict[str, int] = {}

    def to_dict(self) -> dict:
        """Convert stats to dictionary."""
        return {
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "total_tags": self.total_tags,
            "nodes_by_type": self.nodes_by_type,
            "avg_degree": self.avg_degree,
            "max_degree": self.max_degree,
            "isolated_nodes": self.isolated_nodes,
        }


class VaultGraph:
    def __init__(self):
        self._nodes: dict[str, MemoryNode] = {}
        self._entities: dict[str, EntityNode] = {}
        self._extraction_results: dict[str, ExtractionResult] = {}
        self._adjacency: dict[str, set[str]] = defaultdict(set)
        self._entity_adjacency: dict[str, set[str]] = defaultdict(set)

        # Indexes for O(1) lookups
        self._tag_index: dict[str, set[str]] = defaultdict(set)
        self._type_index: dict[MemoryType, set[str]] = defaultdict(set)
        self._backlink_index: dict[str, set[str]] = defaultdict(set)

        # Statistics
        self._stats = GraphStats()

    def add_node(self, node: MemoryNode):
        self._nodes[node.id] = node
        for link in node.links:
            self._adjacency[node.id].add(link)

        # Update indexes
        for tag in node.tags:
            self._tag_index[tag].add(node.id)
        self._type_index[node.memory_type].add(node.id)
        for target_id in node.links:
            self._backlink_index[target_id].add(node.id)

        self._update_stats()

    def add_entity(self, entity: EntityNode):
        """Add an extracted entity to the graph."""
        self._entities[entity.id] = entity
        if entity.source_memory_id in self._nodes:
            self._entity_adjacency[entity.source_memory_id].add(entity.id)
        for related_id in entity.related_entities:
            self._entity_adjacency[entity.id].add(related_id)

    def add_extraction_result(self, result: ExtractionResult):
        """Add all entities from an extraction result."""
        self._extraction_results[result.memory_id] = result
        for entity in result.all_entities():
            self.add_entity(entity)

    def get_entities_for_memory(self, memory_id: str) -> list[EntityNode]:
        """Get all entities extracted from a specific memory."""
        if memory_id in self._extraction_results:
            return self._extraction_results[memory_id].all_entities()
        return []

    def get_entity(self, entity_id: str) -> EntityNode | None:
        """Get a specific entity by ID."""
        return self._entities.get(entity_id)

    def get_entities_by_type(self, entity_type) -> list[EntityNode]:
        """Get all entities of a specific type."""
        return [e for e in self._entities.values() if e.entity_type == entity_type]

    def build_backlinks(self):
        """Populate backlinks after all nodes are loaded."""
        backlink_map: dict[str, list[str]] = defaultdict(list)
        for node_id, targets in self._adjacency.items():
            for target in targets:
                backlink_map[target].append(node_id)
        for node_id, node in self._nodes.items():
            node.backlinks = backlink_map.get(node_id, [])

    def get(self, node_id: str) -> MemoryNode | None:
        return self._nodes.get(node_id)

    def neighbors(
        self, node_id: str, depth: int = 1, include_backlinks: bool = True
    ) -> list[MemoryNode]:
        """BFS traversal up to `depth` hops, following links and optionally backlinks."""
        if depth <= 0:
            return []

        visited = {node_id}
        current_level = {node_id}

        for _ in range(depth):
            next_level = set()
            for nid in current_level:
                next_level.update(self._adjacency.get(nid, set()))
                if include_backlinks:
                    next_level.update(self._backlink_index.get(nid, set()))
            next_level -= visited
            visited.update(next_level)
            current_level = next_level

        visited.discard(node_id)
        return [self._nodes[nid] for nid in visited if nid in self._nodes]

    def find_path(
        self, from_id: str, to_id: str, max_depth: int = 10
    ) -> list[MemoryNode] | None:
        """Find shortest path between two nodes using BFS.

        Args:
            from_id: Starting node ID.
            to_id: Target node ID.
            max_depth: Maximum search depth.

        Returns:
            List of MemoryNode objects forming the path (including start and end),
            or None if no path exists.
        """
        if from_id == to_id:
            node = self._nodes.get(from_id)
            return [node] if node else None

        if from_id not in self._nodes or to_id not in self._nodes:
            return None

        visited = {from_id}
        # Queue of (current_id, path_so_far)
        from collections import deque

        queue: deque[tuple[str, list[str]]] = deque([(from_id, [from_id])])

        while queue:
            curr_id, path = queue.popleft()
            if len(path) > max_depth:
                continue

            # Get all neighbors (forward links + backlinks)
            neighbor_ids = set(self._adjacency.get(curr_id, set()))
            neighbor_ids.update(self._backlink_index.get(curr_id, set()))

            for nid in neighbor_ids:
                if nid == to_id:
                    full_path = path + [nid]
                    return [self._nodes[pid] for pid in full_path if pid in self._nodes]
                if nid not in visited:
                    visited.add(nid)
                    queue.append((nid, path + [nid]))

        return None

    def remove_node(self, node_id: str) -> bool:
        """Remove a node from the graph and update all indexes."""
        node = self._nodes.get(node_id)
        if not node:
            return False

        # Remove from nodes and adjacency
        del self._nodes[node_id]
        if node_id in self._adjacency:
            del self._adjacency[node_id]

        # Remove references in other adjacency lists
        for adj_set in self._adjacency.values():
            adj_set.discard(node_id)

        # Remove from tag index
        for tag in node.tags:
            self._tag_index[tag].discard(node_id)
            if not self._tag_index[tag]:
                del self._tag_index[tag]

        # Remove from type index
        self._type_index[node.memory_type].discard(node_id)
        if not self._type_index[node.memory_type]:
            del self._type_index[node.memory_type]

        # Remove from backlink index
        for target_id in node.links:
            self._backlink_index[target_id].discard(node_id)
            if not self._backlink_index[target_id]:
                del self._backlink_index[target_id]

        self._update_stats()
        return True

    def all_nodes(self) -> list[MemoryNode]:
        """Return all memory nodes in the graph."""
        return list(self._nodes.values())

    def all_entities(self) -> list[EntityNode]:
        """Return all entities in the graph."""
        return list(self._entities.values())

    def filter(self, tags=None, memory_type=None, min_salience=0.0) -> list[MemoryNode]:
        results = []
        for node in self._nodes.values():
            if tags and not set(tags).intersection(node.tags):
                continue
            if memory_type and node.memory_type != memory_type:
                continue
            if node.salience < min_salience:
                continue
            results.append(node)
        return sorted(results, key=lambda n: n.salience, reverse=True)

    # --- Index-based lookup methods ---

    def get_by_tag(self, tag: str) -> list[MemoryNode]:
        """Get all nodes with a specific tag (O(1) lookup)."""
        node_ids = self._tag_index.get(tag, set())
        return [self._nodes[nid] for nid in node_ids if nid in self._nodes]

    def get_by_tags(self, tags: list[str], match_all: bool = False) -> list[MemoryNode]:
        """Get nodes matching tags.

        Args:
            tags: List of tags to search for.
            match_all: If True, node must have all tags; if False, any tag.
        """
        if not tags:
            return []

        if match_all:
            node_id_sets = [self._tag_index.get(tag, set()) for tag in tags]
            matching_ids = set.intersection(*node_id_sets) if node_id_sets else set()
        else:
            matching_ids = set()
            for tag in tags:
                matching_ids.update(self._tag_index.get(tag, set()))

        return [self._nodes[nid] for nid in matching_ids if nid in self._nodes]

    def get_by_type(self, memory_type: MemoryType) -> list[MemoryNode]:
        """Get all nodes of a specific type (O(1) lookup)."""
        node_ids = self._type_index.get(memory_type, set())
        return [self._nodes[nid] for nid in node_ids if nid in self._nodes]

    def get_backlinks(self, node_id: str) -> list[MemoryNode]:
        """Get all nodes that link to this node (O(1) lookup)."""
        source_ids = self._backlink_index.get(node_id, set())
        return [self._nodes[sid] for sid in source_ids if sid in self._nodes]

    def get_all_tags(self) -> list[str]:
        """Get all unique tags in the graph."""
        return sorted(self._tag_index.keys())

    def get_tag_counts(self) -> dict[str, int]:
        """Get count of nodes for each tag."""
        return {tag: len(node_ids) for tag, node_ids in self._tag_index.items()}

    def get_type_counts(self) -> dict[str, int]:
        """Get count of nodes for each memory type."""
        return {
            mem_type.value: len(node_ids)
            for mem_type, node_ids in self._type_index.items()
        }

    def get_stats(self) -> GraphStats:
        """Get graph statistics."""
        return self._stats

    def rebuild_indexes(self):
        """Rebuild all indexes from scratch."""
        self._tag_index.clear()
        self._type_index.clear()
        self._backlink_index.clear()

        for node in self._nodes.values():
            for tag in node.tags:
                self._tag_index[tag].add(node.id)
            self._type_index[node.memory_type].add(node.id)
            for target_id in node.links:
                self._backlink_index[target_id].add(node.id)

        self._update_stats()

    def validate_indexes(self) -> dict[str, bool]:
        """Validate that all indexes are consistent."""
        results = {
            "tag_index": True,
            "type_index": True,
            "backlink_index": True,
        }

        for tag, node_ids in self._tag_index.items():
            for nid in node_ids:
                node = self._nodes.get(nid)
                if not node or tag not in node.tags:
                    results["tag_index"] = False
                    break

        for mem_type, node_ids in self._type_index.items():
            for nid in node_ids:
                node = self._nodes.get(nid)
                if not node or node.memory_type != mem_type:
                    results["type_index"] = False
                    break

        for target_id, source_ids in self._backlink_index.items():
            for sid in source_ids:
                source = self._nodes.get(sid)
                if not source or target_id not in source.links:
                    results["backlink_index"] = False
                    break

        return results

    def clear(self):
        """Clear all nodes and indexes."""
        self._nodes.clear()
        self._adjacency.clear()
        self._entities.clear()
        self._extraction_results.clear()
        self._entity_adjacency.clear()
        self._tag_index.clear()
        self._type_index.clear()
        self._backlink_index.clear()
        self._stats = GraphStats()

    def _update_stats(self):
        """Update graph statistics."""
        self._stats.total_nodes = len(self._nodes)
        self._stats.total_tags = len(self._tag_index)
        total_edges = sum(len(node.links) for node in self._nodes.values())
        self._stats.total_edges = total_edges
        self._stats.nodes_by_type = self.get_type_counts()

        degrees = [
            len(node.links) + len(self._backlink_index.get(node.id, set()))
            for node in self._nodes.values()
        ]
        if degrees:
            self._stats.avg_degree = sum(degrees) / len(degrees)
            self._stats.max_degree = max(degrees)
            self._stats.isolated_nodes = sum(1 for d in degrees if d == 0)
        else:
            self._stats.avg_degree = 0.0
            self._stats.max_degree = 0
            self._stats.isolated_nodes = 0
