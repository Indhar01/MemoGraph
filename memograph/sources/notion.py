"""``NotionSource`` — a Notion workspace as a Markdown source.

Phase 2 adapter. Internal-integration-token auth only (the operator
creates a Notion integration at notion.so/profile/integrations and
shares the relevant pages with it). Public Notion OAuth is Phase 5+.

The adapter pulls pages via the existing :class:`NotionClient`
wrapper at
:mod:`memograph.integrations.notion.client`, converts the block tree
to Markdown with a minimal renderer (this module's
:func:`_blocks_to_markdown`), and presents each page as one
``Document``. Writing back is **out of scope** for Phase 2 — Notion's
block-edit API requires non-trivial diffing to avoid lossy round-trips,
and we don't yet have the conflict-resolution UX for that. Calls to
:meth:`NotionSource.write_document` raise :class:`SourceReadOnlyError`.

Doc-ids are the Notion page id (32-char hex, no dashes). Stable for
the lifetime of the page; survives renames. We do NOT use the page
title as the id because Notion titles aren't unique and can change.

Config shape (in ``SourceConfig.params``):

.. code-block:: json

    {
      "auth_token": "secret_...",     // optional; falls back to NOTION_API_TOKEN env
      "database_id": "abc123...",     // optional; restricts to one database
      "filter_query": "..."            // optional; passed to /search
    }

Optional dependency: ``notion-client``. The adapter imports lazily
so the base ``pip install memograph`` does not pull Notion SDKs.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from memograph.sources.base import (
    ChangeEvent,
    Document,
    DocumentEncoding,
    DocumentRef,
    Source,
    SourceAuthError,
    SourceConfig,
    SourceError,
    SourceHealth,
    SourceHealthStatus,
    SourceNotFoundError,
    SourceReadOnlyError,
    SyncMode,
    SyncStats,
    WriteResult,
)

logger = logging.getLogger(__name__)


class NotionSource(Source):
    """Notion workspace as a read-only Markdown source.

    Construction is cheap — the Notion client is built lazily on
    first I/O. The integration token is resolved at construction
    time only insofar as we need to choose between
    ``params['auth_token']`` and the ambient ``NOTION_API_TOKEN``
    env var.
    """

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        self._auth_token: str | None = config.params.get("auth_token") or None
        self._database_id: str | None = config.params.get("database_id") or None
        self._filter_query: str | None = config.params.get("filter_query") or None
        self._client: Any = None  # lazy NotionClient

    # --- lazy client wiring ---

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from memograph.integrations.notion.client import NotionClient
        except ImportError as exc:
            raise SourceError(
                "NotionSource requires notion-client. "
                "Install with: pip install 'memograph[sources-notion]'"
            ) from exc
        try:
            self._client = NotionClient(auth_token=self._auth_token)
        except ValueError as exc:
            # NotionClient raises ValueError when no auth token is
            # found. Translate to SourceAuthError so the routes
            # surface 401 instead of 500.
            raise SourceAuthError(str(exc)) from exc
        return self._client

    # --- document ops ---

    async def list_documents(self) -> AsyncIterator[DocumentRef]:
        import asyncio

        client = self._ensure_client()

        def _list() -> list[dict[str, Any]]:
            try:
                if self._database_id:
                    return client.list_pages(database_id=self._database_id)
                # search_pages returns only pages with filter_type="page".
                # Default behaviour: the operator's integration sees
                # every page that's been explicitly shared with it.
                return client.search_pages(query=self._filter_query)
            except Exception as exc:  # noqa: BLE001
                if _is_notion_auth_error(exc):
                    raise SourceAuthError(str(exc)) from exc
                raise SourceError(f"Notion list failed: {exc}") from exc

        pages = await asyncio.to_thread(_list)
        for page in pages:
            ref = _ref_from_page(page)
            if ref is not None:
                yield ref

    async def read_document(self, doc_id: str) -> Document:
        import asyncio

        client = self._ensure_client()

        def _fetch() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            try:
                page = client.get_page(doc_id)
                blocks = client.get_all_blocks(doc_id)
            except Exception as exc:  # noqa: BLE001
                if _is_notion_not_found(exc):
                    raise SourceNotFoundError(
                        f"Notion page not found: {doc_id}"
                    ) from exc
                if _is_notion_auth_error(exc):
                    raise SourceAuthError(str(exc)) from exc
                raise SourceError(f"Notion fetch failed: {exc}") from exc
            return page, blocks

        page, blocks = await asyncio.to_thread(_fetch)
        ref = _ref_from_page(page)
        if ref is None:
            raise SourceError(
                f"Notion page {doc_id} has no usable title; cannot index"
            )
        content = _blocks_to_markdown(blocks)
        return Document(
            ref=ref,
            content=content,
            encoding=DocumentEncoding.MARKDOWN,
        )

    async def write_document(self, doc: Document) -> WriteResult:
        # Phase 2: read-only. The block-edit story (avoid clobbering
        # Notion's rich formatting from a flat markdown write) needs
        # a diffing layer that isn't in scope yet. Callers should
        # check :attr:`supports_writes` before invoking.
        raise SourceReadOnlyError(
            "NotionSource is read-only in Phase 2. "
            "Writes round-tripping back to Notion are gated on a "
            "block-diff layer planned for a later phase."
        )

    async def watch(self) -> AsyncIterator[ChangeEvent]:
        # Notion's webhook API is in beta and requires Enterprise
        # plan. Polling-only for now.
        if False:  # pragma: no cover
            yield ChangeEvent.__new__(ChangeEvent)  # type: ignore[call-arg]
        return

    async def materialize_to_vault(self, vault_path: Path) -> SyncStats:
        """Pull every visible page into ``vault_path``.

        File layout: one ``<title>.md`` per page. If titles collide,
        the page id is appended (``<title> (abc123).md``). We DO NOT
        recreate Notion's page hierarchy as nested folders — the
        graph already lives inside the markdown via wikilinks, and
        flattening avoids the directory-explosion problem on big
        workspaces.
        """
        started = perf_counter()
        vault = Path(vault_path).expanduser()
        vault.mkdir(parents=True, exist_ok=True)

        seen = written = 0
        used_names: dict[str, int] = {}
        async for ref in self.list_documents():
            seen += 1
            base = _safe_filename(ref.title) or ref.doc_id
            name = f"{base}.md"
            if name in used_names:
                used_names[name] += 1
                # Disambiguate with the first 6 chars of the page id.
                name = f"{base} ({ref.doc_id[:6]}).md"
            used_names[name] = 1
            dst = vault / name
            if dst.exists():
                dst_stat = dst.stat()
                if datetime.fromtimestamp(
                    dst_stat.st_mtime, tz=timezone.utc
                ) >= ref.modified_at:
                    continue
            try:
                doc = await self.read_document(ref.doc_id)
            except SourceError as exc:
                logger.warning(
                    "skipping Notion page %s: %s", ref.doc_id, exc
                )
                continue
            assert isinstance(doc.content, str)
            dst.write_text(doc.content, encoding="utf-8")
            written += 1

        return SyncStats(
            mode=SyncMode.FULL,
            documents_seen=seen,
            documents_written=written,
            documents_deleted=0,
            duration_seconds=perf_counter() - started,
        )

    async def health(self) -> SourceHealth:
        import asyncio

        try:
            client = self._ensure_client()
        except SourceAuthError as exc:
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )
        except SourceError as exc:
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )

        def _probe() -> bool:
            try:
                return client.test_connection()
            except Exception:  # noqa: BLE001
                return False

        ok = await asyncio.to_thread(_probe)
        return SourceHealth(
            status=SourceHealthStatus.OK if ok else SourceHealthStatus.FAILED,
            checked_at=datetime.now(timezone.utc),
            last_successful_sync_at=(
                datetime.now(timezone.utc) if ok else None
            ),
            last_error=None if ok else "Notion API connection probe failed",
        )

    @property
    def supports_writes(self) -> bool:
        # See write_document docstring.
        return False

    @property
    def supports_watch(self) -> bool:
        # Polling-only in Phase 2.
        return False


# --- helpers ---


def _ref_from_page(page: dict[str, Any]) -> DocumentRef | None:
    """Build a :class:`DocumentRef` from a Notion page payload.

    Returns ``None`` for pages that lack a title we can use — these
    are typically database row containers that have no
    ``properties.title`` and aren't user-facing documents anyway.
    """
    page_id = page.get("id")
    if not page_id:
        return None
    page_id_clean = page_id.replace("-", "")
    title = _extract_title(page) or page_id_clean[:8]
    last_edited = page.get("last_edited_time")
    try:
        modified = (
            datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
            if last_edited
            else datetime.now(timezone.utc)
        )
    except (ValueError, AttributeError):
        modified = datetime.now(timezone.utc)
    return DocumentRef(
        doc_id=page_id_clean,
        title=title,
        modified_at=modified,
        size_bytes=None,
        metadata={
            "notion_page_id": page_id,
            "url": page.get("url"),
            "archived": page.get("archived", False),
        },
    )


def _extract_title(page: dict[str, Any]) -> str | None:
    """Best-effort title extraction from a Notion page payload.

    The Notion API returns titles in different places depending on
    whether the page lives directly in a workspace or inside a
    database. We try both shapes.
    """
    props = page.get("properties", {}) or {}
    for prop in props.values():
        if not isinstance(prop, dict):
            continue
        if prop.get("type") == "title":
            parts = prop.get("title", []) or []
            text = "".join(
                (p.get("plain_text", "") or "") for p in parts
            ).strip()
            if text:
                return text
    # Workspace pages sometimes expose title at top level.
    title = page.get("title")
    if isinstance(title, list):
        text = "".join(
            (p.get("plain_text", "") or "") for p in title
        ).strip()
        if text:
            return text
    return None


def _blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Render a flat list of Notion blocks as Markdown.

    Supports the common block types: paragraph, headings (1-3),
    bulleted/numbered list items, to-do, quote, code, divider. Other
    block types render as a placeholder line so the operator can see
    something was there. Nested children are NOT recursively
    rendered in Phase 2 — that requires a separate API call per
    block and significantly inflates sync cost; flat rendering
    captures ~95% of practical content.
    """
    out: list[str] = []
    for block in blocks:
        btype = block.get("type")
        data = block.get(btype, {}) or {}
        rich = data.get("rich_text", []) or []
        text = "".join((p.get("plain_text", "") or "") for p in rich)

        if btype == "paragraph":
            out.append(text)
        elif btype == "heading_1":
            out.append(f"# {text}")
        elif btype == "heading_2":
            out.append(f"## {text}")
        elif btype == "heading_3":
            out.append(f"### {text}")
        elif btype == "bulleted_list_item":
            out.append(f"- {text}")
        elif btype == "numbered_list_item":
            # We don't track numbering across siblings — Markdown
            # auto-numbers, so "1." everywhere is fine.
            out.append(f"1. {text}")
        elif btype == "to_do":
            checked = data.get("checked", False)
            out.append(f"- [{'x' if checked else ' '}] {text}")
        elif btype == "quote":
            out.append(f"> {text}")
        elif btype == "code":
            lang = data.get("language", "") or ""
            out.append(f"```{lang}\n{text}\n```")
        elif btype == "divider":
            out.append("---")
        elif btype is None:
            continue
        else:
            # Unknown block type — emit a HTML comment so the user
            # knows something was there without it disturbing prose.
            out.append(f"<!-- notion: {btype} block (not rendered) -->")
    return "\n\n".join(s for s in out if s)


def _safe_filename(title: str) -> str:
    """Best-effort filesystem-safe filename from a Notion page title.

    Strips characters that are illegal on Windows / cause sync
    headaches with OneDrive. Truncates long titles to keep paths
    under typical NTFS limits.
    """
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in title)
    cleaned = cleaned.strip(" .")
    return cleaned[:120]


def _is_notion_auth_error(exc: BaseException) -> bool:
    """Coarse classifier for Notion auth failures.

    notion-client raises :class:`APIResponseError` with ``.status``
    on HTTP failures. 401/403 → auth; everything else → generic.
    We sniff via attribute access to avoid importing notion_client
    at module load.
    """
    status = getattr(exc, "status", None) or getattr(exc, "code", None)
    if isinstance(status, int):
        return status in {401, 403}
    if isinstance(status, str):
        return status in {"unauthorized", "restricted_resource"}
    return False


def _is_notion_not_found(exc: BaseException) -> bool:
    status = getattr(exc, "status", None) or getattr(exc, "code", None)
    if isinstance(status, int):
        return status == 404
    if isinstance(status, str):
        return status in {"object_not_found", "not_found"}
    return False


__all__ = ["NotionSource"]
