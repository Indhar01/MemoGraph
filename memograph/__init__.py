from .core.access_tracker import AccessTracker
from .core.enums import EntityType, MemoryType
from .core.extractor import SmartAutoOrganizer
from .core.gam_retriever import GAMRetriever
from .core.gam_scorer import GAMConfig, GAMScorer
from .core.kernel import MemoryKernel

try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("memograph")
    except PackageNotFoundError:
        __version__ = "0.1.0"
except ImportError:
    __version__ = "0.1.0"
__all__ = [
    "MemoryKernel",
    "MemoryType",
    "SmartAutoOrganizer",
    "EntityType",
    "GAMConfig",
    "GAMScorer",
    "GAMRetriever",
    "AccessTracker",
]
