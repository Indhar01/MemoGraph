"""``Source`` ABC and shared types.

A :class:`Source` is an adapter for one external location where
Markdown documents live. The retrieval pipeline doesn't talk to
sources directly — it always operates on a local materialized vault.
The :class:`Source` contract is the bridge:

* :meth:`Source.list_documents` — async iterator of every doc the
  source can see, used at registration time and for periodic
  reconciliation.
* :meth:`Source.read_document` — fetch one doc by id.
* :meth:`Source.write_document` — push a local edit back to the
  source (where supported; read-only sources raise
  :class:`SourceReadOnlyError`).
* :meth:`Source.watch` — long-lived async iterator of
  :class:`ChangeEvent` that lets the sync worker re-materialize only
  what changed.
* :meth:`Source.materialize_to_vault` — one-shot pull-everything,
  used on registration and on operator-triggered "force resync".
* :meth:`Source.health` — periodic probe surfaced via
  ``GET /api/v1/sources/{id}/health``.

The :class:`Source` ABC intentionally does NOT extend
:class:`memograph.integrations.base.IntegrationBase`. ``IntegrationBase``
models bidirectional sync between two systems that both own state
(Obsidian ↔ vault); a :class:`Source` instead models a single
location that *is* the state. The two contracts don't compose
cleanly — every attempt at a shared parent forced one side or the
other into ``NotImplementedError`` for half its methods.

Concrete adapters wrapping existing integrations
(``NotionSource``, ``ObsidianSource``) will hold an
``IntegrationBase`` instance internally rather than subclass both.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SourceKind(str, enum.Enum):
    """Discriminator for source adapters.

    Stored on disk as a string in source configs, so values are
    stable forever — never rename an existing variant. Adding a new
    variant only requires registering an adapter in
    :class:`memograph.sources.registry.SourceRegistry`; downstream
    code reads ``SourceKind.value`` and never the variant name.
    """

    LOCAL = "local"
    GDRIVE = "gdrive"
    ONEDRIVE = "onedrive"
    S3 = "s3"
    NOTION = "notion"


class SourceHealthStatus(str, enum.Enum):
    """Three-state health for a source.

    Maps to the Prometheus gauge
    ``memograph_source_health{tenant,source_kind}`` with values
    ``0`` (FAILED), ``1`` (DEGRADED), ``2`` (OK). Numeric mapping
    is in :meth:`SourceHealthStatus.numeric`.
    """

    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"

    def numeric(self) -> int:
        return {
            SourceHealthStatus.FAILED: 0,
            SourceHealthStatus.DEGRADED: 1,
            SourceHealthStatus.OK: 2,
        }[self]


class SyncMode(str, enum.Enum):
    """Whether a sync re-fetches everything or only changed items."""

    FULL = "full"
    INCREMENTAL = "incremental"


class ChangeKind(str, enum.Enum):
    """Kinds of change events emitted by :meth:`Source.watch`."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    # Some sources (Drive, OneDrive) emit move events as a single
    # operation; we model them as a separate kind so consumers don't
    # have to infer a move from a delete+create pair.
    MOVED = "moved"


class SourceError(RuntimeError):
    """Base for all source-related errors. Use subclasses below."""


class SourceReadOnlyError(SourceError):
    """The source does not support writes (e.g. a read-only S3 bucket)."""


class SourceAuthError(SourceError):
    """Auth failed — typically an expired or revoked OAuth token.

    Routes surface this as 401 to the caller and the sync worker
    pauses retries on the source until an operator re-authorises.
    """


class SourceNotFoundError(SourceError):
    """Requested document does not exist at the source."""


class DocumentEncoding(str, enum.Enum):
    """How :attr:`Document.content` is encoded.

    Markdown is the dominant case; binary is reserved for adapters
    that may surface PDFs / images. The kernel ignores binary
    documents at ingest time today — surfacing them as a separate
    encoding lets a future importer pick them up without changing
    the source contract again.
    """

    MARKDOWN = "markdown"
    BINARY = "binary"


@dataclass(frozen=True)
class DocumentRef:
    """Lightweight handle to a document.

    Returned from :meth:`Source.list_documents` and
    :meth:`Source.watch`. Read the full body with
    :meth:`Source.read_document`.
    """

    doc_id: str
    """Source-stable id. Opaque; only the source itself dereferences it."""

    title: str
    """Human-readable title. Used for the local filename and as a fallback."""

    modified_at: datetime
    """UTC timestamp of the source-side last modification."""

    size_bytes: int | None = None
    """Body size if cheaply available; ``None`` if the adapter does not know."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Arbitrary adapter-specific metadata (Drive file id, S3 etag, etc.)."""


@dataclass(frozen=True)
class Document:
    """A document body plus its ref. Returned from :meth:`Source.read_document`."""

    ref: DocumentRef
    content: str | bytes
    encoding: DocumentEncoding = DocumentEncoding.MARKDOWN


@dataclass(frozen=True)
class WriteResult:
    """Outcome of :meth:`Source.write_document`."""

    doc_id: str
    """The doc id after the write — may differ from the input ref for
    sources that mint ids server-side."""

    version: str | None = None
    """Source-side version / etag / revision, if exposed."""

    written_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ChangeEvent:
    """One source-side change. Emitted by :meth:`Source.watch`."""

    kind: ChangeKind
    doc_id: str
    occurred_at: datetime
    # Present for UPDATED / MOVED, absent for DELETED, optional for
    # CREATED (some adapters batch and don't ship the body inline).
    ref: DocumentRef | None = None
    # MOVED only: the doc id before the move, where the source
    # actually re-keys on move (Drive does not; OneDrive does).
    old_doc_id: str | None = None


@dataclass(frozen=True)
class SyncStats:
    """Summary of one sync run. Returned from
    :meth:`Source.materialize_to_vault` and from the sync worker."""

    mode: SyncMode
    documents_seen: int
    documents_written: int
    documents_deleted: int
    conflicts: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class SourceHealth:
    """Snapshot returned by :meth:`Source.health`.

    Routes return this verbatim under
    ``GET /api/v1/sources/{id}/health``. Cheap to compute; sources
    should cache the underlying probe and avoid hammering the
    upstream API on every health-check request.
    """

    status: SourceHealthStatus
    checked_at: datetime
    last_successful_sync_at: datetime | None = None
    last_error: str | None = None
    documents_total: int | None = None


@dataclass(frozen=True)
class SourceConfig:
    """Persisted configuration for a source.

    Stored as JSON under ``<tenant_root>/<tenant_id>/.sources/<source_id>.json``
    by :class:`memograph.sources.registry.SourceRegistry`. Tokens are
    not in this object — those go through the encrypted token store
    in ``memograph.sources.oauth.token_store``. ``params`` is the
    only adapter-specific field; everything else is uniform.

    The ``params`` dict should be JSON-serialisable. Adapters that
    need typed config define their own dataclass and convert.
    """

    source_id: str
    kind: SourceKind
    display_name: str
    tenant_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Source(ABC):
    """Abstract source of memories.

    Subclass per backend. Adapters MUST be safe to construct with
    just a :class:`SourceConfig` — no I/O in ``__init__``. The
    registry constructs sources synchronously and then awaits a
    one-shot :meth:`materialize_to_vault` for the first warmup;
    everything else is lazy.
    """

    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    # --- identity ---

    @property
    def source_id(self) -> str:
        return self.config.source_id

    @property
    def kind(self) -> SourceKind:
        return self.config.kind

    @property
    def tenant_id(self) -> str | None:
        return self.config.tenant_id

    # --- document ops ---

    @abstractmethod
    async def list_documents(self) -> AsyncIterator[DocumentRef]:
        """Async iterator over every document the source can see.

        Used at registration and for periodic reconciliation. Adapters
        SHOULD page through large collections rather than buffer the
        whole list. The order is unspecified; consumers must not rely
        on it for stability.
        """
        ...

    @abstractmethod
    async def read_document(self, doc_id: str) -> Document:
        """Fetch one document by id.

        Raises :class:`SourceNotFoundError` if the id is unknown;
        :class:`SourceAuthError` if the token has expired; any other
        adapter error is wrapped in :class:`SourceError`.
        """
        ...

    @abstractmethod
    async def write_document(self, doc: Document) -> WriteResult:
        """Push a local edit back to the source.

        Raises :class:`SourceReadOnlyError` for sources that don't
        support writes. Callers are expected to check
        :attr:`supports_writes` before invoking; the explicit
        exception is the safety net for adapters that change
        capability at runtime (an S3 bucket with read-only IAM).
        """
        ...

    # --- change feed ---

    @abstractmethod
    async def watch(self) -> AsyncIterator[ChangeEvent]:
        """Long-lived async iterator of source-side change events.

        Adapters implement this with whatever the upstream offers:
        Drive uses watch channels, OneDrive uses webhook
        subscriptions, S3 uses EventBridge, Notion uses long-poll.
        The local filesystem source uses :mod:`watchdog`.

        Implementations MUST reconnect on transient failure and
        only raise :class:`SourceAuthError` (which the worker
        treats as a hard stop until reauth).
        """
        ...

    # --- one-shot sync ---

    @abstractmethod
    async def materialize_to_vault(self, vault_path: Path) -> SyncStats:
        """Pull every document into a local vault directory.

        Idempotent: calling twice with the same ``vault_path`` is
        equivalent to running once. Adapters SHOULD skip writes
        when the local file is already up to date by some adapter-
        appropriate check (mtime, etag, hash).
        """
        ...

    # --- health ---

    @abstractmethod
    async def health(self) -> SourceHealth:
        """Probe the source and return a current-state snapshot.

        Cheap to call. Long-running checks should be cached behind
        a small TTL inside the adapter.
        """
        ...

    # --- capability flags ---

    @property
    def supports_writes(self) -> bool:
        """True if :meth:`write_document` is implemented (default True).

        Adapters that are read-only override this to False so the
        UI can hide the write affordances.
        """
        return True

    @property
    def supports_watch(self) -> bool:
        """True if :meth:`watch` emits real events (default True).

        Set False on adapters that can only poll. The sync worker
        uses this to decide between subscription-driven and
        cron-driven reconciliation.
        """
        return True

    # --- representation ---

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} "
            f"id={self.source_id!r} "
            f"kind={self.kind.value} "
            f"tenant={self.tenant_id!r}>"
        )


__all__ = [
    "ChangeEvent",
    "ChangeKind",
    "Document",
    "DocumentEncoding",
    "DocumentRef",
    "Source",
    "SourceAuthError",
    "SourceConfig",
    "SourceError",
    "SourceHealth",
    "SourceHealthStatus",
    "SourceKind",
    "SourceNotFoundError",
    "SourceReadOnlyError",
    "SyncMode",
    "SyncStats",
    "WriteResult",
]
