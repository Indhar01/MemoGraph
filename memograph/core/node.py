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
