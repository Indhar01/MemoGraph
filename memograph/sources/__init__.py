"""Source adapters — pluggable backends for where memories live.

Implements the v1.1+ storage adapter roadmap from
[ADR 0002](../../docs/adr/0002-storage-adapter-strategy.md). A
:class:`Source` is an adapter that knows how to enumerate, read, and
write Markdown documents at some external location (local filesystem,
S3 bucket, Google Drive folder, OneDrive site, Notion workspace, …).

The retrieval pipeline (:class:`memograph.core.kernel.MemoryKernel`)
still operates on a canonical local Markdown vault — cloud sources
``materialize_to_vault`` into a local cache and incremental change
events flow back into that cache. This preserves the
markdown-as-source-of-truth invariant called out in ADR 0002 and
keeps offline operation trivial.

Sources are feature-flagged behind ``MEMOGRAPH_SOURCES_ENABLED=1``
through Phase 1. When the flag is off (the default), every
``memograph.sources`` import still works — only the
``/api/v1/sources`` routes are gated. This lets the package land
incrementally without changing behavior for existing installs.
"""

from __future__ import annotations

from memograph.sources.base import (
    ChangeEvent,
    ChangeKind,
    Document,
    DocumentRef,
    Source,
    SourceConfig,
    SourceError,
    SourceHealth,
    SourceHealthStatus,
    SourceKind,
    SyncMode,
    SyncStats,
    WriteResult,
)
from memograph.sources.local import LocalSource

# Phase 2+ adapters are not re-exported eagerly here — importing
# them would pull in boto3 / notion-client at package import time
# and break the optional-dependency promise. Consumers that know
# they need an adapter should import it directly:
#     from memograph.sources.s3 import S3Source
#     from memograph.sources.notion import NotionSource
# The registry's default factory does this lazily for routes.

__all__ = [
    "ChangeEvent",
    "ChangeKind",
    "Document",
    "DocumentRef",
    "LocalSource",
    "Source",
    "SourceConfig",
    "SourceError",
    "SourceHealth",
    "SourceHealthStatus",
    "SourceKind",
    "SyncMode",
    "SyncStats",
    "WriteResult",
]
