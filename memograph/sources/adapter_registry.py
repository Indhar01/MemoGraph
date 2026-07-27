"""Source adapter registry — the extension seam for source kinds.

Public seam for the open-core split. The public package ships the
``LOCAL`` adapter; optional/commercial adapters (S3, and the Nango-backed
cloud kinds) register themselves here at import time via
:func:`register_source_adapter`. :func:`memograph.sources.registry.default_source_factory`
consults this map, so no adapter is hardcoded into the factory anymore.

A plugin (e.g. ``memograph-enterprise``) registers its adapters from its
``memograph.plugins`` entry point, so a stock ``pip install memograph`` sees
only ``LOCAL`` and returns a clear "no adapter registered" error for kinds it
doesn't ship.

Adapters are plain factories ``Callable[[SourceConfig], Source]``. Kinds that
need extra construction context (the cloud OAuth kinds need a NangoClient) are
NOT built through this map directly — see
``SourceRegistry._build_with_context`` — but they still register a marker
factory here so ``list``/validation code can tell a known-but-context-bound
kind from a genuinely-unregistered one.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable

from memograph.sources.base import Source, SourceConfig, SourceKind

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

SourceAdapterFactory = Callable[[SourceConfig], Source]

# Module-level registry. Guarded by a lock because plugins may register from
# an import that races app startup in threaded test harnesses.
_lock = threading.RLock()
_adapters: dict[SourceKind, SourceAdapterFactory] = {}


def register_source_adapter(
    kind: SourceKind, factory: SourceAdapterFactory, *, override: bool = False
) -> None:
    """Register a factory for a :class:`SourceKind`.

    Idempotent-friendly: re-registering the same kind is a no-op unless
    ``override=True`` (used by tests). Logs at INFO so plugin activation is
    visible in server startup logs.
    """
    with _lock:
        if kind in _adapters and not override:
            logger.debug("source adapter for %s already registered; skipping", kind.value)
            return
        _adapters[kind] = factory
        logger.info("registered source adapter: kind=%s", kind.value)


def get_source_adapter(kind: SourceKind) -> SourceAdapterFactory | None:
    """Return the factory for ``kind`` or None if no adapter is registered."""
    with _lock:
        return _adapters.get(kind)


def is_registered(kind: SourceKind) -> bool:
    with _lock:
        return kind in _adapters


def registered_kinds() -> list[SourceKind]:
    with _lock:
        return list(_adapters.keys())


def _reset_for_tests() -> None:
    """Drop all registrations except the built-ins. Test helper."""
    with _lock:
        _adapters.clear()
    _register_builtins()


def _register_builtins() -> None:
    """Register adapters the public package ships. Currently only LOCAL."""
    from memograph.sources.local import LocalSource

    register_source_adapter(SourceKind.LOCAL, LocalSource, override=True)


# Register built-ins at import time so LOCAL always works out of the box.
_register_builtins()


__all__ = [
    "SourceAdapterFactory",
    "get_source_adapter",
    "is_registered",
    "register_source_adapter",
    "registered_kinds",
]