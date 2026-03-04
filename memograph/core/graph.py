# core/graph.py
from collections import defaultdict, deque

from .node import MemoryNode


class VaultGraph:
    def __init__(self):
        self._nodes: dict[str, MemoryNode] = {}
        self._adjacency: dict[str, set[str]] = defaultdict(set)

    def add_node(self, node: MemoryNode):
        self._nodes[node.id] = node
        for link in node.links:
            self._adjacency[node.id].add(link)

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

    def neighbors(self, node_id: str, depth: int = 1) -> list[MemoryNode]:
        """BFS traversal up to `depth` hops, following both links and backlinks."""
        visited, queue = set(), deque([(node_id, 0)])
        result = []
        while queue:
            curr_id, d = queue.popleft()
            if curr_id in visited or d > depth:
                continue
            visited.add(curr_id)
            if node := self._nodes.get(curr_id):
                if curr_id != node_id:
                    result.append(node)
                if d < depth:
                    for nxt in self._adjacency[curr_id] | set(node.backlinks):
                        queue.append((nxt, d + 1))
        return result

    def remove_node(self, node_id: str):
        """Remove a node from the graph (e.g., when a file is deleted)."""
        if node_id in self._nodes:
            # Remove the node itself
            del self._nodes[node_id]

            # Remove from adjacency list
            if node_id in self._adjacency:
                del self._adjacency[node_id]

            # Remove any references to this node in other adjacency lists
            for adj_set in self._adjacency.values():
                adj_set.discard(node_id)

    def all_nodes(self) -> list[MemoryNode]:
        """Return all nodes in the graph."""
        return list(self._nodes.values())

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
