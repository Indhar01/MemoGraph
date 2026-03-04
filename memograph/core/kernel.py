import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .compressor import TokenCompressor
from .enums import MemoryType
from .graph import VaultGraph
from .indexer import VaultIndexer
from .node import MemoryNode
from .retriever import HybridRetriever


class MemoryKernel:
    def __init__(self, vault_path: str, embedding_adapter=None):
        self.vault_path = Path(vault_path).expanduser()
        self.vault_path.mkdir(parents=True, exist_ok=True)

        self.graph = VaultGraph()
        self.embedding_adapter = embedding_adapter
        self.indexer = VaultIndexer(self.vault_path, embedding_adapter=embedding_adapter)
        self.retriever = HybridRetriever(self.graph, embedding_adapter=embedding_adapter)

    @staticmethod
    def _normalize_tags(tags: list[str] | None) -> list[str]:
        if not tags:
            return []
        normalized = []
        for tag in tags:
            clean = tag.strip().lstrip("#")
            if clean:
                normalized.append(clean)
        return normalized

    @staticmethod
    def _slugify(text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
        return slug or datetime.now(timezone.utc).strftime("memory-%Y%m%d-%H%M%S")

    def ingest(self, force: bool = False) -> dict[str, int]:
        """
        Ingests all memories from the vault.
        """
        self.graph = VaultGraph()
        indexed, skipped = self.indexer.index(self.graph, force=force)
        self.retriever = HybridRetriever(self.graph, embedding_adapter=self.retriever.embeddings)
        total = len(self.graph._nodes)
        return {"indexed": indexed, "skipped": skipped, "total": total}

    def remember(
        self,
        title: str,
        content: str,
        memory_type: MemoryType = MemoryType.FACT,
        tags: list[str] = None,
    ):
        """
        Creates a new memory.
        """
        normalized_tags = self._normalize_tags(tags)
        slug = self._slugify(title)
        file_path = self.vault_path / f"{slug}.md"

        counter = 2
        while file_path.exists():
            file_path = self.vault_path / f"{slug}-{counter}.md"
            counter += 1

        created_at = datetime.now(timezone.utc).isoformat()
        tags_line = " ".join(f"#{tag}" for tag in normalized_tags)

        payload = {
            "title": title,
            "memory_type": memory_type.value,
            "created": created_at,
            "salience": 1.0,
        }
        frontmatter = "---\n" + yaml.safe_dump(payload, sort_keys=False).strip() + "\n---\n\n"

        body = content.strip()
        if tags_line:
            body = f"{body}\n\n{tags_line}"

        file_path.write_text(frontmatter + body + "\n", encoding="utf-8")
        return str(file_path)

    def context_window(
        self,
        query: str,
        tags: list[str] = None,
        depth: int = 2,
        top_k: int = 8,
        token_limit: int = 2048,
    ) -> str:
        """
        Retrieves relevant context from the memory vault.
        """
        nodes = self.retrieve_nodes(query=query, tags=tags, depth=depth, top_k=top_k)
        compressor = TokenCompressor(token_limit=token_limit)
        return compressor.compress(nodes)

    def retrieve_nodes(
        self,
        query: str,
        tags: list[str] = None,
        depth: int = 2,
        top_k: int = 8,
    ) -> list[MemoryNode]:
        normalized_tags = self._normalize_tags(tags)

        if not self.graph._nodes:
            self.ingest()

        query_words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
        seed_ids = []
        for node in self.graph._nodes.values():
            haystack = f"{node.title} {node.content}".lower()
            if any(word in haystack for word in query_words):
                seed_ids.append(node.id)

        return self.retriever.retrieve(
            query=query,
            seed_ids=seed_ids,
            tags=normalized_tags,
            depth=depth,
            top_k=top_k,
        )
