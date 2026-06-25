"""MemoGraph — graph-based memory for LLMs.

The names in ``__all__`` are MemoGraph's public Python surface and are
covered by the deprecation policy documented in ``CONTRIBUTING.md`` and
the contract in ``docs/MIGRATION_0.X_TO_1.0.md``. Anything imported from
a submodule path (``memograph.core.kernel``, ``memograph.storage.vault``,
etc.) still works but is NOT covered — move to the top-level imports
below for stability across major versions.
"""

from importlib.metadata import PackageNotFoundError, version

from .core.access_tracker import AccessTracker
from .core.config import MemographConfig
from .core.enums import EntityType, MemoryType
from .core.extractor import SmartAutoOrganizer
from .core.gam_retriever import GAMRetriever
from .core.gam_scorer import GAMConfig, GAMScorer
from .core.graph import VaultGraph
from .core.kernel import MemoryKernel, MemoryQuery, SearchOptions
from .core.node import MemoryNode
from .core.retriever import HybridRetriever
from .storage.vault import VaultStorage

try:
    __version__ = version("memograph")
except PackageNotFoundError:
    # Editable install before the package is registered, or a pure source
    # checkout being imported directly. The lockstep with pyproject.toml
    # is intentionally loose here — real consumers come through pip.
    __version__ = "0.0.0+local"

__all__ = [
    # Core API — the kernel and its query builder
    "MemoryKernel",
    "MemoryQuery",
    "SearchOptions",
    # Data model
    "MemoryNode",
    "MemoryType",
    "EntityType",
    # Graph + retrieval
    "VaultGraph",
    "HybridRetriever",
    "GAMRetriever",
    "GAMScorer",
    "GAMConfig",
    # Vault I/O
    "VaultStorage",
    # Subsystems
    "AccessTracker",
    "SmartAutoOrganizer",
    "MemographConfig",
    # Package metadata
    "__version__",
]
