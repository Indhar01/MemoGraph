# core/indexer.py
import json
from pathlib import Path

from .graph import VaultGraph
from .parser import parse_file

CACHE_FILE = ".recallgraph_cache.json"
GRAPH_CACHE_FILE = ".recallgraph_graph.json"
EMBEDDINGS_CACHE_FILE = ".recallgraph_embeddings.json"


class VaultIndexer:
    def __init__(self, vault_root: Path, embedding_adapter=None):
        self.root = vault_root
        self.cache_path = vault_root / CACHE_FILE
        self.graph_cache_path = vault_root / GRAPH_CACHE_FILE
        self.embeddings_cache_path = vault_root / EMBEDDINGS_CACHE_FILE
        self.embedding_adapter = embedding_adapter
        self._mtime_cache: dict[str, float] = self._load_cache()
        self._embeddings_cache: dict[str, list[float]] = self._load_embeddings_cache()

    def _load_cache(self) -> dict[str, float]:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_cache(self, mtimes: dict[str, float]):
        self.cache_path.write_text(json.dumps(mtimes))
        self._mtime_cache = mtimes

    def _load_embeddings_cache(self) -> dict[str, list[float]]:
        """Load cached embeddings from disk."""
        if self.embeddings_cache_path.exists():
            try:
                return json.loads(self.embeddings_cache_path.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_embeddings_cache(self):
        """Save embeddings cache to disk."""
        self.embeddings_cache_path.write_text(json.dumps(self._embeddings_cache))

    def _load_graph_from_cache(self, graph: VaultGraph) -> bool:
        """Load previously indexed graph state from cache. Returns True if successful."""
        if not self.graph_cache_path.exists():
            return False

        try:
            cache_data = json.loads(self.graph_cache_path.read_text())
            # Reconstruct nodes from cached data
            for node_data in cache_data.get("nodes", []):
                # Import here to avoid circular dependency
                from .enums import MemoryType
                from .node import MemoryNode

                node = MemoryNode(
                    id=node_data["id"],
                    title=node_data["title"],
                    content=node_data["content"],
                    memory_type=MemoryType[node_data["memory_type"]],
                    tags=node_data["tags"],
                    links=node_data["links"],
                    backlinks=node_data["backlinks"],
                    salience=node_data["salience"],
                    access_count=node_data["access_count"],
                    source_path=node_data.get("source_path"),
                )
                # Restore embedding if available
                if node.id in self._embeddings_cache:
                    node.embedding = self._embeddings_cache[node.id]
                graph.add_node(node)
            return True
        except (json.JSONDecodeError, KeyError, ValueError):
            return False

    def _save_graph_to_cache(self, graph: VaultGraph):
        """Save graph state to cache for faster subsequent loads."""
        nodes_data = []
        for node in graph.all_nodes():
            nodes_data.append(
                {
                    "id": node.id,
                    "title": node.title,
                    "content": node.content,
                    "memory_type": node.memory_type.name,
                    "tags": node.tags,
                    "links": node.links,
                    "backlinks": node.backlinks,
                    "salience": node.salience,
                    "access_count": node.access_count,
                    "source_path": node.source_path,
                }
            )

        cache_data = {"nodes": nodes_data}
        self.graph_cache_path.write_text(json.dumps(cache_data, indent=2))

    def index(self, graph: VaultGraph, force=False) -> tuple[int, int]:
        """Returns (indexed, skipped) counts."""
        new_mtimes = {}
        indexed = skipped = 0

        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)

        # Load existing graph from cache if not forcing rebuild
        if not force and self._load_graph_from_cache(graph):
            # Graph loaded from cache, now check for changes
            current_files = set()

            for md_file in self.root.rglob("*.md"):
                if md_file.name in [CACHE_FILE, GRAPH_CACHE_FILE, EMBEDDINGS_CACHE_FILE]:
                    continue

                rel = md_file.relative_to(self.root).as_posix()
                current_files.add(rel)
                mtime = md_file.stat().st_mtime
                new_mtimes[rel] = mtime

                unchanged = self._mtime_cache.get(rel) == mtime
                if unchanged:
                    skipped += 1
                else:
                    # File is new or modified - parse and update
                    node = parse_file(md_file, self.root)
                    self._generate_and_cache_embedding(node)
                    graph.add_node(node)
                    indexed += 1

            # Remove nodes for deleted files
            cached_files = set(self._mtime_cache.keys())
            deleted_files = cached_files - current_files
            for deleted_rel in deleted_files:
                # Extract node ID from relative path
                node_id = Path(deleted_rel).stem
                if graph.get(node_id):
                    graph.remove_node(node_id)
        else:
            # Force rebuild or no cache - parse all files
            for md_file in self.root.rglob("*.md"):
                if md_file.name in [CACHE_FILE, GRAPH_CACHE_FILE, EMBEDDINGS_CACHE_FILE]:
                    continue

                rel = md_file.relative_to(self.root).as_posix()
                mtime = md_file.stat().st_mtime
                new_mtimes[rel] = mtime

                node = parse_file(md_file, self.root)
                self._generate_and_cache_embedding(node)
                graph.add_node(node)
                indexed += 1

        graph.build_backlinks()
        self._save_cache(new_mtimes)
        self._save_graph_to_cache(graph)
        self._save_embeddings_cache()
        return indexed, skipped

    def _generate_and_cache_embedding(self, node):
        """Generate and cache embedding for a node if adapter is available."""
        if self.embedding_adapter:
            # Check if we already have a cached embedding
            if node.id in self._embeddings_cache:
                node.embedding = self._embeddings_cache[node.id]
            else:
                # Generate new embedding
                node.embedding = self.embedding_adapter.embed(node.content)
                self._embeddings_cache[node.id] = node.embedding
