"""Vault hierarchy resolution: map a memory to its on-disk relative path.

Pure, side-effect-free path computation — no I/O. The kernel uses a resolver
to decide WHERE a new note is filed; the file is written via
``VaultStorage.write`` (which is nested-path-safe). Because a note's identity
lives in frontmatter ``id`` (decoupled from path, see
docs/ADR_SELF_ORGANIZING_HIERARCHY.md), the chosen folder is a presentation
concern only — moving a note never changes its id or breaks ``[[wikilinks]]``.

Strategies (public):

- ``flat``    -> ``<slug>.md``                 (default; historical behavior)
- ``by_type`` -> ``<memory_type>/<slug>.md``   (deterministic, zero-intelligence)

Selected via ``MEMOGRAPH_HIERARCHY_STRATEGY`` or the ``hierarchy_strategy``
kernel argument. ``by_topic`` / ``by_ontology`` are intentionally NOT here —
they belong to the product layer (see docs/PUBLIC_VS_PRIVATE_SPLIT.md) and can
be registered as custom resolvers via the constructor.
"""

from __future__ import annotations

import re
from typing import Callable

from .enums import MemoryType

# A resolver takes (slug, memory_type, tags) and returns a relative POSIX path
# (always ending in ``.md``). Kept as a simple callable signature so the
# product layer can plug in smarter strategies without subclassing.
StrategyFn = Callable[[str, MemoryType, list[str]], str]

_VALID_STRATEGIES = ("flat", "by_type")

# memory_type folder names are the enum values (episodic/semantic/procedural/fact).
# Guarded against path escapes even though the enum is closed.
_SAFE_SEGMENT_RE = re.compile(r"[^a-z0-9._-]+")


def _safe_segment(text: str) -> str:
    """Normalize a single path segment: lowercase, hyphenated, no separators."""
    seg = _SAFE_SEGMENT_RE.sub("-", text.strip().lower()).strip("-.")
    return seg or "misc"


def _flat(slug: str, memory_type: MemoryType, tags: list[str]) -> str:
    return f"{slug}.md"


def _by_type(slug: str, memory_type: MemoryType, tags: list[str]) -> str:
    folder = _safe_segment(memory_type.value)
    return f"{folder}/{slug}.md"


_BUILTIN: dict[str, StrategyFn] = {
    "flat": _flat,
    "by_type": _by_type,
}


class HierarchyResolver:
    """Resolve a memory to a relative vault path under a chosen strategy.

    Example:
        >>> r = HierarchyResolver("by_type")
        >>> r.relative_path_for("python-async", MemoryType.SEMANTIC, [])
        'semantic/python-async.md'
        >>> HierarchyResolver("flat").relative_path_for("x", MemoryType.FACT, [])
        'x.md'
    """

    def __init__(
        self,
        strategy: str = "flat",
        custom: StrategyFn | None = None,
    ):
        # A custom callable (e.g. the product layer's by_ontology resolver)
        # takes precedence over the named strategy.
        if custom is not None:
            self.strategy_name = strategy or "custom"
            self._fn = custom
            return
        name = (strategy or "flat").lower().strip()
        if name not in _BUILTIN:
            raise ValueError(
                f"unknown hierarchy strategy {strategy!r}; "
                f"valid: {', '.join(_VALID_STRATEGIES)}"
            )
        self.strategy_name = name
        self._fn = _BUILTIN[name]

    def relative_path_for(
        self,
        slug: str,
        memory_type: MemoryType,
        tags: list[str] | None = None,
    ) -> str:
        """Return the relative POSIX ``.md`` path this note should live at."""
        if not slug:
            raise ValueError("slug must be non-empty")
        rel = self._fn(slug, memory_type, tags or [])
        # Defense in depth: the result must be a relative .md path with no
        # traversal, matching VaultStorage._safe_path's contract.
        if rel.startswith(("/", "\\")) or ".." in rel.split("/"):
            raise ValueError(f"resolver produced an unsafe path: {rel!r}")
        if not rel.endswith(".md"):
            raise ValueError(f"resolver must return a .md path, got: {rel!r}")
        return rel


__all__ = ["HierarchyResolver", "StrategyFn"]
