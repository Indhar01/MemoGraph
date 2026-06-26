"""``LocalSource`` — a Markdown directory on the local filesystem.

The canonical case from ADR 0002: a folder of ``.md`` files. The
adapter wraps :class:`memograph.storage.vault.VaultStorage` so the
existing path-traversal guards, capacity caps, and write logic are
reused verbatim.

Two practical configurations:

1. **Source IS the vault.** ``params["path"]`` equals the vault path
   the kernel will operate on. :meth:`materialize_to_vault` is a
   no-op verification step. This is the default for solo installs
   and for users pointing at a desktop-sync-client folder
   (OneDrive, Drive for Desktop, Dropbox).

2. **Source is a separate directory copied into the vault.** Less
   common but supported — useful for read-only "library" folders
   that get imported into a working vault. :meth:`materialize_to_vault`
   then copies ``*.md`` files into the vault path.

Mode 1 is detected when the resolved source path equals the
resolved vault path; otherwise mode 2 applies.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from memograph.sources.base import (
    ChangeEvent,
    Document,
    DocumentEncoding,
    DocumentRef,
    Source,
    SourceConfig,
    SourceError,
    SourceHealth,
    SourceHealthStatus,
    SourceNotFoundError,
    SyncMode,
    SyncStats,
    WriteResult,
)
from memograph.storage.vault import VaultStorage

logger = logging.getLogger(__name__)


class LocalSource(Source):
    """Local filesystem source. Backed by :class:`VaultStorage`.

    The constructor is cheap — it does not scan the directory. The
    first call to :meth:`list_documents` or
    :meth:`materialize_to_vault` is when I/O happens.
    """

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        path = config.params.get("path")
        if not path:
            raise SourceError(
                f"LocalSource {config.source_id!r} requires "
                "params['path']; got empty/missing value"
            )
        # Resolve once at construction so subsequent ops don't repeat
        # the syscall. VaultStorage will create the directory if it
        # doesn't exist, which is the intended behavior on first
        # registration of a brand-new vault path.
        self._path: Path = Path(path).expanduser().resolve()
        # Lazy: VaultStorage constructor creates the directory and
        # enforces caps. We don't want to do that at __init__ time
        # for adapters that may fail other validation later — but
        # for LocalSource the directory creation IS the validation.
        self._storage: VaultStorage | None = None

    # --- internal helpers ---

    def _ensure_storage(self) -> VaultStorage:
        if self._storage is None:
            self._storage = VaultStorage(self._path)
        return self._storage

    def _doc_id_from_path(self, path: Path) -> str:
        """Stable, relative doc id for a file inside the source root.

        We use the POSIX-style relative path so doc ids round-trip
        unchanged across Windows / Linux. The vault is canonically a
        flat directory today but the source contract allows nesting,
        so the doc id preserves the relative structure.
        """
        rel = path.relative_to(self._path)
        return rel.as_posix()

    def _path_from_doc_id(self, doc_id: str) -> Path:
        """Inverse of :meth:`_doc_id_from_path`, with traversal guard.

        Raises :class:`SourceError` if the resolved path escapes the
        source root — defense in depth against a caller passing a
        crafted id like ``../../etc/passwd``.
        """
        candidate = (self._path / doc_id).resolve()
        try:
            candidate.relative_to(self._path)
        except ValueError as exc:
            raise SourceError(
                f"doc_id {doc_id!r} resolves outside the source root"
            ) from exc
        return candidate

    def _ref_for_path(self, path: Path) -> DocumentRef:
        stat = path.stat()
        return DocumentRef(
            doc_id=self._doc_id_from_path(path),
            title=path.stem,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            size_bytes=stat.st_size,
            metadata={"path": str(path)},
        )

    # --- Source interface ---

    async def list_documents(self) -> AsyncIterator[DocumentRef]:
        storage = self._ensure_storage()
        # markdown_files() is sync + may walk a large tree. Yield to
        # the event loop between batches so a 100k-doc vault doesn't
        # starve other coroutines.
        files = await asyncio.to_thread(storage.markdown_files)
        for i, md in enumerate(files):
            yield self._ref_for_path(md)
            if i % 100 == 99:
                await asyncio.sleep(0)

    async def read_document(self, doc_id: str) -> Document:
        path = self._path_from_doc_id(doc_id)
        if not path.exists():
            raise SourceNotFoundError(f"document {doc_id!r} not found")

        def _read() -> tuple[str, DocumentRef]:
            content = path.read_text(encoding="utf-8")
            return content, self._ref_for_path(path)

        content, ref = await asyncio.to_thread(_read)
        return Document(ref=ref, content=content, encoding=DocumentEncoding.MARKDOWN)

    async def write_document(self, doc: Document) -> WriteResult:
        if doc.encoding is DocumentEncoding.BINARY:
            # Binary writes are out of scope until an importer or
            # frontend feature requires them; fail loudly rather
            # than silently corrupting the vault.
            raise SourceError(
                f"LocalSource does not write binary documents "
                f"(doc_id={doc.ref.doc_id!r})"
            )
        path = self._path_from_doc_id(doc.ref.doc_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> WriteResult:
            assert isinstance(doc.content, str)
            path.write_text(doc.content, encoding="utf-8")
            stat = path.stat()
            return WriteResult(
                doc_id=doc.ref.doc_id,
                # mtime nanoseconds doubles as a poor-man's etag.
                version=str(stat.st_mtime_ns),
                written_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )

        return await asyncio.to_thread(_write)

    async def watch(self) -> AsyncIterator[ChangeEvent]:
        # Filesystem watching via :mod:`watchdog` is a separate,
        # heavier integration. Phase 1 ships LocalSource with
        # :attr:`supports_watch` = False; the sync worker falls back
        # to periodic polling against :meth:`list_documents`. This
        # is fine for local sources because the kernel already
        # re-reads files on its own ingest path.
        if False:  # pragma: no cover — never iterates
            yield ChangeEvent.__new__(ChangeEvent)  # type: ignore[call-arg]
        return

    async def materialize_to_vault(self, vault_path: Path) -> SyncStats:
        """If ``vault_path`` is the source itself: no-op verification.
        If different: copy ``*.md`` files into ``vault_path``.

        Either way the return value reflects how many docs the kernel
        will end up seeing at ``vault_path`` after this call.
        """
        started = perf_counter()
        vault_resolved = Path(vault_path).expanduser().resolve()
        same_dir = vault_resolved == self._path

        if same_dir:
            storage = self._ensure_storage()
            files = await asyncio.to_thread(storage.markdown_files)
            return SyncStats(
                mode=SyncMode.FULL,
                documents_seen=len(files),
                documents_written=0,
                documents_deleted=0,
                duration_seconds=perf_counter() - started,
            )

        # Different paths — copy through.
        vault_resolved.mkdir(parents=True, exist_ok=True)
        storage = self._ensure_storage()
        files = await asyncio.to_thread(storage.markdown_files)
        written = 0
        for src in files:
            rel = src.relative_to(self._path)
            dst = vault_resolved / rel
            # Skip if destination is up to date by mtime — same
            # heuristic the kernel's indexer uses on its own cache.
            if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, src, dst)
            written += 1
        return SyncStats(
            mode=SyncMode.FULL,
            documents_seen=len(files),
            documents_written=written,
            documents_deleted=0,
            duration_seconds=perf_counter() - started,
        )

    async def health(self) -> SourceHealth:
        # Local source health is trivial: does the directory exist
        # and is it readable? Anything more elaborate (disk full,
        # permissions) shows up as a write failure at write time and
        # there's no value in pre-probing the entire vault on every
        # health check.
        try:
            exists = await asyncio.to_thread(self._path.exists)
            if not exists:
                return SourceHealth(
                    status=SourceHealthStatus.FAILED,
                    checked_at=datetime.now(timezone.utc),
                    last_error=f"source path does not exist: {self._path}",
                )
            storage = self._ensure_storage()
            files = await asyncio.to_thread(storage.markdown_files)
            return SourceHealth(
                status=SourceHealthStatus.OK,
                checked_at=datetime.now(timezone.utc),
                last_successful_sync_at=datetime.now(timezone.utc),
                documents_total=len(files),
            )
        except OSError as exc:
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )

    @property
    def supports_watch(self) -> bool:
        # Phase 1: poll. Phase 2+ may switch to watchdog.
        return False


__all__ = ["LocalSource"]
