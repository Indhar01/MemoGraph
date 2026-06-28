"""``NangoBackedSource`` — one adapter for every OAuth cloud kind.

Replaces the per-provider :mod:`gdrive`, :mod:`onedrive`, and
:mod:`notion` adapters. All three kinds funnel through Nango's HTTP
proxy, which injects the right access token and handles refresh, so
the only provider-specific code left is:

* the search/list endpoint URL,
* the per-file metadata-to-:class:`DocumentRef` mapping,
* the export trick for Google Docs (``/export?mimeType=text/markdown``),
* the Notion blocks-to-markdown renderer.

Everything else — auth, retries, token storage — is Nango's problem.

Config (in :attr:`SourceConfig.params`):

.. code-block:: json

    {
      "nango_connection_id": "<from the connection-creation webhook>",
      "folder_id": "...",       // optional, kind-specific scoping
      "drive_id":  "b!...",     // OneDrive: SharePoint library id
      "sync_interval_seconds": 600
    }

The webhook populates ``nango_connection_id`` automatically; operators
who script source creation must supply it themselves.

Read-only — all three providers ship in read-only mode for now.
:meth:`write_document` raises :class:`SourceReadOnlyError`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote

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
    SourceKind,
    SourceNotFoundError,
    SourceReadOnlyError,
    SyncMode,
    SyncStats,
    WriteResult,
)
from memograph.sources.nango_client import (
    KIND_TO_PROVIDER_KEY,
    NangoClient,
)

logger = logging.getLogger(__name__)


# Provider-specific MIME hints used to decide how to render a fetched
# document. Kept here (not in the client) because they're a property of
# the adapter, not of Nango.
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_MARKDOWN_MIMES = frozenset({
    "text/markdown",
    "text/x-markdown",
    "text/plain",
})
ONEDRIVE_MARKDOWN_MIMES = frozenset({
    "text/markdown",
    "text/x-markdown",
    "text/plain",
})


class NangoBackedSource(Source):
    """Single adapter that serves GDrive, OneDrive, and Notion via Nango."""

    def __init__(self, config: SourceConfig, *, nango_client: NangoClient) -> None:
        super().__init__(config)
        if config.kind not in KIND_TO_PROVIDER_KEY:
            raise SourceError(
                f"NangoBackedSource cannot serve kind {config.kind.value!r}; "
                f"supported kinds: {sorted(k.value for k in KIND_TO_PROVIDER_KEY)}"
            )
        self._client = nango_client
        connection_id = config.params.get("nango_connection_id")
        if not connection_id or not isinstance(connection_id, str):
            raise SourceError(
                f"NangoBackedSource {config.source_id!r} is missing "
                "params['nango_connection_id']. The webhook handler "
                "writes this automatically; scripted creation must "
                "supply it."
            )
        self._connection_id: str = connection_id
        self._folder_id: str | None = config.params.get("folder_id") or None
        self._drive_id: str | None = config.params.get("drive_id") or None

    @property
    def supports_writes(self) -> bool:
        return False

    @property
    def supports_watch(self) -> bool:
        return False

    # --- document operations ---------------------------------------------

    async def list_documents(self) -> AsyncIterator[DocumentRef]:
        if self.config.kind is SourceKind.GDRIVE:
            async for ref in self._list_drive():
                yield ref
        elif self.config.kind is SourceKind.ONEDRIVE:
            async for ref in self._list_onedrive():
                yield ref
        elif self.config.kind is SourceKind.NOTION:
            async for ref in self._list_notion():
                yield ref
        else:  # pragma: no cover — guarded in __init__
            raise SourceError(f"unsupported kind {self.config.kind.value!r}")

    async def _list_drive(self) -> AsyncIterator[DocumentRef]:
        mime_clause = " or ".join(
            f"mimeType = '{m}'" for m in (*GOOGLE_MARKDOWN_MIMES, GOOGLE_DOC_MIME)
        )
        q_parts = [f"({mime_clause})", "trashed = false"]
        if self._folder_id:
            q_parts.append(f"'{self._folder_id}' in parents")
        query = " and ".join(q_parts)
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "q": query,
                "fields": (
                    "nextPageToken,"
                    "files(id,name,mimeType,modifiedTime,size,md5Checksum)"
                ),
                "pageSize": "100",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = await self._client.proxy_get(
                connection_id=self._connection_id,
                kind=SourceKind.GDRIVE,
                path="drive/v3/files",
                params=params,
            )
            self._raise_for_proxy_status(resp, "Drive list")
            data = resp.json()
            for f in data.get("files", []) or []:
                yield _ref_from_drive(f)
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    async def _list_onedrive(self) -> AsyncIterator[DocumentRef]:
        prefix = (
            f"drives/{quote(self._drive_id, safe='')}"
            if self._drive_id
            else "me/drive"
        )
        path = (
            f"{prefix}/items/{quote(self._folder_id, safe='')}/children"
            if self._folder_id
            else f"{prefix}/root/children"
        )
        next_path: str | None = path
        first_params: dict[str, Any] | None = {
            "$select": "id,name,size,file,folder,lastModifiedDateTime",
            "$top": "100",
        }
        while next_path:
            # The first call uses our composed path + params; subsequent
            # pages come from @odata.nextLink which is fully qualified.
            if next_path.startswith("http"):
                resp = await self._client.proxy_get(
                    connection_id=self._connection_id,
                    kind=SourceKind.ONEDRIVE,
                    path=next_path.split("://", 1)[1].split("/", 1)[1],
                )
            else:
                resp = await self._client.proxy_get(
                    connection_id=self._connection_id,
                    kind=SourceKind.ONEDRIVE,
                    path=next_path,
                    params=first_params,
                )
                first_params = None
            self._raise_for_proxy_status(resp, "OneDrive list")
            data = resp.json()
            for item in data.get("value", []) or []:
                if "folder" in item:
                    continue
                if not _onedrive_is_text(item):
                    continue
                yield _ref_from_onedrive(item)
            next_path = data.get("@odata.nextLink")

    async def _list_notion(self) -> AsyncIterator[DocumentRef]:
        """Enumerate Notion pages reachable to the connected integration.

        Two strategies, picked by config:

        * If ``params['database_id']`` is set, query that single
          database (``POST /v1/databases/{id}/query``) — useful when
          the operator only wants one notebook indexed.
        * Otherwise, use Notion's search endpoint
          (``POST /v1/search`` with ``filter.value=page``) which
          returns every page the integration has been granted access
          to. This is the default after Connect UI registers a fresh
          source; the wizard never collects a database_id.

        Both endpoints are POSTs, paginated by ``start_cursor`` /
        ``has_more`` / ``next_cursor``.
        """
        database_id = self.config.params.get("database_id")
        next_cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if next_cursor:
                body["start_cursor"] = next_cursor
            using_search = not database_id
            if database_id:
                path = f"v1/databases/{quote(database_id, safe='')}/query"
            else:
                path = "v1/search"
                body["filter"] = {"value": "page", "property": "object"}
            resp = await self._client.proxy_post(
                connection_id=self._connection_id,
                kind=SourceKind.NOTION,
                path=path,
                json=body,
            )
            self._raise_for_proxy_status(resp, "Notion list")
            data = resp.json()
            for page in data.get("results", []) or []:
                # /v1/search can return mixed page+database objects even
                # with the filter — guard the search path only. The
                # database-query path always yields pages.
                if using_search and page.get("object") != "page":
                    continue
                yield _ref_from_notion_page(page)
            if not data.get("has_more"):
                break
            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break

    async def read_document(self, doc_id: str) -> Document:
        if self.config.kind is SourceKind.GDRIVE:
            return await self._read_drive(doc_id)
        if self.config.kind is SourceKind.ONEDRIVE:
            return await self._read_onedrive(doc_id)
        if self.config.kind is SourceKind.NOTION:
            return await self._read_notion(doc_id)
        raise SourceError(  # pragma: no cover
            f"unsupported kind {self.config.kind.value!r}"
        )

    async def _read_drive(self, doc_id: str) -> Document:
        meta_resp = await self._client.proxy_get(
            connection_id=self._connection_id,
            kind=SourceKind.GDRIVE,
            path=f"drive/v3/files/{quote(doc_id, safe='')}",
            params={"fields": "id,name,mimeType,modifiedTime,size,md5Checksum"},
        )
        self._raise_for_proxy_status(meta_resp, "Drive metadata", doc_id=doc_id)
        meta = meta_resp.json()
        mime = meta.get("mimeType", "")
        if mime == GOOGLE_DOC_MIME:
            content_bytes = await self._client.proxy_get_bytes(
                connection_id=self._connection_id,
                kind=SourceKind.GDRIVE,
                path=f"drive/v3/files/{quote(doc_id, safe='')}/export",
                params={"mimeType": "text/markdown"},
            )
        else:
            content_bytes = await self._client.proxy_get_bytes(
                connection_id=self._connection_id,
                kind=SourceKind.GDRIVE,
                path=f"drive/v3/files/{quote(doc_id, safe='')}",
                params={"alt": "media"},
            )
        return Document(
            ref=_ref_from_drive(meta),
            content=_decode_utf8(content_bytes, doc_id),
            encoding=DocumentEncoding.MARKDOWN,
        )

    async def _read_onedrive(self, doc_id: str) -> Document:
        prefix = (
            f"drives/{quote(self._drive_id, safe='')}"
            if self._drive_id
            else "me/drive"
        )
        meta_path = f"{prefix}/items/{quote(doc_id, safe='')}"
        meta_resp = await self._client.proxy_get(
            connection_id=self._connection_id,
            kind=SourceKind.ONEDRIVE,
            path=meta_path,
            params={"$select": "id,name,size,file,lastModifiedDateTime"},
        )
        self._raise_for_proxy_status(meta_resp, "OneDrive metadata", doc_id=doc_id)
        meta = meta_resp.json()
        content_bytes = await self._client.proxy_get_bytes(
            connection_id=self._connection_id,
            kind=SourceKind.ONEDRIVE,
            path=f"{meta_path}/content",
        )
        return Document(
            ref=_ref_from_onedrive(meta),
            content=_decode_utf8(content_bytes, doc_id),
            encoding=DocumentEncoding.MARKDOWN,
        )

    async def _read_notion(self, doc_id: str) -> Document:
        # Page metadata.
        page_resp = await self._client.proxy_get(
            connection_id=self._connection_id,
            kind=SourceKind.NOTION,
            path=f"v1/pages/{quote(doc_id, safe='')}",
        )
        self._raise_for_proxy_status(page_resp, "Notion page", doc_id=doc_id)
        page_meta = page_resp.json()
        # Walk the block children and render to markdown.
        blocks = await self._fetch_notion_blocks(doc_id)
        content = _render_notion_blocks(blocks)
        return Document(
            ref=_ref_from_notion_page(page_meta),
            content=content,
            encoding=DocumentEncoding.MARKDOWN,
        )

    async def _fetch_notion_blocks(self, page_id: str) -> list[dict[str, Any]]:
        all_blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            resp = await self._client.proxy_get(
                connection_id=self._connection_id,
                kind=SourceKind.NOTION,
                path=f"v1/blocks/{quote(page_id, safe='')}/children",
                params=params,
            )
            self._raise_for_proxy_status(resp, "Notion blocks", doc_id=page_id)
            data = resp.json()
            all_blocks.extend(data.get("results", []) or [])
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return all_blocks

    async def write_document(self, doc: Document) -> WriteResult:
        raise SourceReadOnlyError(
            f"NangoBackedSource ({self.config.kind.value}) is read-only "
            "in this build."
        )

    async def watch(self) -> AsyncIterator[ChangeEvent]:
        # Nango's per-provider webhook support is a v2 follow-up; for
        # now SyncScheduler polls list_documents on cadence.
        if False:  # pragma: no cover
            yield ChangeEvent.__new__(ChangeEvent)  # type: ignore[call-arg]
        return

    # --- bulk operations --------------------------------------------------

    async def materialize_to_vault(self, vault_path: Path) -> SyncStats:
        started = perf_counter()
        vault = Path(vault_path).expanduser()
        vault.mkdir(parents=True, exist_ok=True)
        seen = written = 0
        async for ref in self.list_documents():
            seen += 1
            safe = _safe_filename(ref.title) or ref.doc_id
            name = safe if safe.lower().endswith((".md", ".txt")) else f"{safe}.md"
            dst = vault / name
            if dst.exists() and datetime.fromtimestamp(
                dst.stat().st_mtime, tz=timezone.utc
            ) >= ref.modified_at:
                continue
            try:
                doc = await self.read_document(ref.doc_id)
            except SourceError as exc:
                logger.warning(
                    "skipping %s/%s: %s",
                    self.config.kind.value,
                    ref.doc_id,
                    exc,
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
        # The cheapest probe is asking Nango directly whether the
        # connection still has valid credentials. No provider round-trip
        # needed for a basic health check.
        try:
            await self._client.get_connection(
                connection_id=self._connection_id, kind=self.config.kind
            )
        except SourceAuthError as exc:
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )
        except SourceNotFoundError as exc:
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=f"Nango connection missing: {exc}",
            )
        except SourceError as exc:
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )
        return SourceHealth(
            status=SourceHealthStatus.OK,
            checked_at=datetime.now(timezone.utc),
            last_successful_sync_at=datetime.now(timezone.utc),
        )

    # --- helpers ----------------------------------------------------------

    def _raise_for_proxy_status(
        self, resp: Any, op: str, *, doc_id: str | None = None
    ) -> None:
        """Translate Nango-proxied provider errors into source errors.

        The proxy forwards provider responses unchanged, so the
        provider's status code is what we see. 401/403 → auth error
        (whether from Nango or the provider, both mean "reconnect");
        404 → not-found; everything else >= 400 → generic source
        error with context for the operator.
        """
        if resp.status_code in (401, 403):
            raise SourceAuthError(
                f"{op} returned {resp.status_code} via Nango "
                f"(connection {self._connection_id}): user may need to reconnect"
            )
        if resp.status_code == 404 and doc_id:
            raise SourceNotFoundError(f"{op}: document {doc_id!r} not found")
        if resp.status_code >= 400:
            try:
                snippet = resp.text[:400]
            except Exception:  # noqa: BLE001
                snippet = "<unreadable>"
            raise SourceError(
                f"{op} failed ({resp.status_code}) via Nango: {snippet}"
            )


# --- pure helpers (no I/O) ------------------------------------------------


def _decode_utf8(content: bytes, doc_id: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError(
            f"document {doc_id!r} is not valid UTF-8"
        ) from exc


def _safe_filename(title: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in title)
    cleaned = cleaned.strip(" .")
    return cleaned[:120]


def _ref_from_drive(f: dict[str, Any]) -> DocumentRef:
    modified_raw = f.get("modifiedTime", "")
    try:
        modified = (
            datetime.fromisoformat(modified_raw.replace("Z", "+00:00"))
            if modified_raw
            else datetime.now(timezone.utc)
        )
    except (TypeError, ValueError):
        modified = datetime.now(timezone.utc)
    size = f.get("size")
    try:
        size_bytes: int | None = int(size) if size is not None else None
    except (TypeError, ValueError):
        size_bytes = None
    return DocumentRef(
        doc_id=f["id"],
        title=f.get("name", f["id"]),
        modified_at=modified,
        size_bytes=size_bytes,
        metadata={
            "mime_type": f.get("mimeType"),
            "md5_checksum": f.get("md5Checksum"),
        },
    )


def _onedrive_is_text(item: dict[str, Any]) -> bool:
    file_info = item.get("file") or {}
    mime = file_info.get("mimeType", "")
    if mime in ONEDRIVE_MARKDOWN_MIMES:
        return True
    name = item.get("name", "").lower()
    return name.endswith(".md") or name.endswith(".txt")


def _ref_from_onedrive(item: dict[str, Any]) -> DocumentRef:
    modified_raw = item.get("lastModifiedDateTime", "")
    try:
        modified = (
            datetime.fromisoformat(modified_raw.replace("Z", "+00:00"))
            if modified_raw
            else datetime.now(timezone.utc)
        )
    except (TypeError, ValueError):
        modified = datetime.now(timezone.utc)
    size = item.get("size")
    try:
        size_bytes: int | None = int(size) if size is not None else None
    except (TypeError, ValueError):
        size_bytes = None
    file_info = item.get("file") or {}
    return DocumentRef(
        doc_id=item["id"],
        title=item.get("name", item["id"]),
        modified_at=modified,
        size_bytes=size_bytes,
        metadata={"mime_type": file_info.get("mimeType")},
    )


def _ref_from_notion_page(page: dict[str, Any]) -> DocumentRef:
    last_edited = page.get("last_edited_time", "")
    try:
        modified = (
            datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
            if last_edited
            else datetime.now(timezone.utc)
        )
    except (TypeError, ValueError):
        modified = datetime.now(timezone.utc)
    title = _extract_notion_title(page) or page.get("id", "")
    return DocumentRef(
        doc_id=page["id"],
        title=title,
        modified_at=modified,
        size_bytes=None,
        metadata={"url": page.get("url")},
    )


def _extract_notion_title(page: dict[str, Any]) -> str | None:
    """Pull the title from a Notion page's properties."""
    props = page.get("properties") or {}
    for value in props.values():
        if isinstance(value, dict) and value.get("type") == "title":
            title_parts = value.get("title") or []
            text = "".join(
                part.get("plain_text", "") for part in title_parts if isinstance(part, dict)
            )
            if text:
                return text
    return None


def _render_notion_blocks(blocks: list[dict[str, Any]]) -> str:
    """Render a flat block list to Markdown.

    Same logic as the previous bespoke Notion adapter, kept narrow:
    paragraphs, headings 1-3, bulleted/numbered list items, to-do,
    quote, code, divider. Unknown block types render as a plain
    text fallback so we don't lose content silently.
    """
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        body = block.get(btype) or {}
        rich = _rich_text(body.get("rich_text") or body.get("text") or [])
        if btype == "paragraph":
            lines.append(rich)
            lines.append("")
        elif btype == "heading_1":
            lines.append(f"# {rich}")
            lines.append("")
        elif btype == "heading_2":
            lines.append(f"## {rich}")
            lines.append("")
        elif btype == "heading_3":
            lines.append(f"### {rich}")
            lines.append("")
        elif btype == "bulleted_list_item":
            lines.append(f"- {rich}")
        elif btype == "numbered_list_item":
            lines.append(f"1. {rich}")
        elif btype == "to_do":
            checked = body.get("checked")
            mark = "x" if checked else " "
            lines.append(f"- [{mark}] {rich}")
        elif btype == "quote":
            lines.append(f"> {rich}")
            lines.append("")
        elif btype == "code":
            lang = body.get("language", "")
            lines.append(f"```{lang}")
            lines.append(rich)
            lines.append("```")
            lines.append("")
        elif btype == "divider":
            lines.append("---")
            lines.append("")
        elif rich:
            # Fallback for unrenderable types — preserve content.
            lines.append(rich)
    return "\n".join(lines).strip() + "\n"


def _rich_text(parts: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("plain_text") or ""
        annotations = part.get("annotations") or {}
        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        link_info = part.get("href")
        if link_info:
            text = f"[{text}]({link_info})"
        out.append(text)
    return "".join(out)


__all__ = ["NangoBackedSource"]
