# core/node.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .enums import MemoryType


@dataclass
class MemoryNode:
    id: str  # Derived from file path (slug)
    title: str
    content: str
    memory_type: MemoryType = MemoryType.SEMANTIC

    # Graph relationships
    links: list[str] = field(default_factory=list)  # Outgoing wikilinks
    backlinks: list[str] = field(default_factory=list)  # Populated by graph
    tags: list[str] = field(default_factory=list)

    # Metadata / reinforcement signals
    salience: float = 1.0  # 0.0–1.0, boosted on access/linking
    access_count: int = 0
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Source file path
    source_path: str | None = None

    # Arbitrary YAML frontmatter passthrough
    frontmatter: dict[str, Any] = field(default_factory=dict)

    # Optional: set by embedding adapter
    embedding: list[float] | None = None

    def to_dict(self, include_graph: bool = False, include_embedding: bool = False) -> dict[str, Any]:
        """
        Serialize the memory node to a dictionary.

        Args:
            include_graph: If True, include links and backlinks. Default: False.
            include_embedding: If True, include embedding vector. Default: False.

        Returns:
            Dictionary representation of the memory node.

        Example:
            >>> node = MemoryNode(id="test", title="Test", content="Content")
            >>> node_dict = node.to_dict()
            >>> print(node_dict["title"])
            Test
        """
        data = {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "memory_type": self.memory_type.value,
            "tags": self.tags,
            "salience": self.salience,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat(),
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "source_path": self.source_path,
            "frontmatter": self.frontmatter,
        }

        if include_graph:
            data["links"] = self.links
            data["backlinks"] = self.backlinks

        if include_embedding and self.embedding is not None:
            data["embedding"] = self.embedding

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryNode":
        """
        Deserialize a memory node from a dictionary.

        Args:
            data: Dictionary containing node data.

        Returns:
            MemoryNode instance.

        Raises:
            ValueError: If required fields are missing.
            TypeError: If field types are incorrect.

        Example:
            >>> data = {
            ...     "id": "test",
            ...     "title": "Test",
            ...     "content": "Content",
            ...     "memory_type": "semantic"
            ... }
            >>> node = MemoryNode.from_dict(data)
            >>> print(node.title)
            Test
        """
        # Validate required fields
        required_fields = ["id", "title", "content"]
        for field_name in required_fields:
            if field_name not in data:
                raise ValueError(
                    f"Missing required field '{field_name}'. "
                    f"Required fields: {', '.join(required_fields)}"
                )

        # Parse memory type
        memory_type = data.get("memory_type", "semantic")
        if isinstance(memory_type, str):
            memory_type = MemoryType(memory_type)
        elif not isinstance(memory_type, MemoryType):
            raise TypeError(
                f"memory_type must be a string or MemoryType enum, got {type(memory_type).__name__}"
            )

        # Parse datetime fields
        def parse_datetime(value: Any, field_name: str) -> datetime:
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return datetime.fromisoformat(value)
            raise TypeError(
                f"{field_name} must be a datetime or ISO format string, got {type(value).__name__}"
            )

        last_accessed = parse_datetime(
            data.get("last_accessed", datetime.now(timezone.utc)),
            "last_accessed"
        )
        created_at = parse_datetime(
            data.get("created_at", datetime.now(timezone.utc)),
            "created_at"
        )
        modified_at = parse_datetime(
            data.get("modified_at", datetime.now(timezone.utc)),
            "modified_at"
        )

        return cls(
            id=data["id"],
            title=data["title"],
            content=data["content"],
            memory_type=memory_type,
            links=data.get("links", []),
            backlinks=data.get("backlinks", []),
            tags=data.get("tags", []),
            salience=data.get("salience", 1.0),
            access_count=data.get("access_count", 0),
            last_accessed=last_accessed,
            created_at=created_at,
            modified_at=modified_at,
            source_path=data.get("source_path"),
            frontmatter=data.get("frontmatter", {}),
            embedding=data.get("embedding"),
        )
