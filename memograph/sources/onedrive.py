"""``OneDriveSource`` — Microsoft OneDrive / SharePoint as a Markdown source.

Phase 4 adapter. Uses Microsoft Graph v1.0 directly via ``httpx`` (no
``msgraph-sdk`` dep — that SDK is heavy and async-unfriendly). The
install footprint is identical to the Drive adapter: ``httpx`` (already
transitive) + ``cryptography`` for the token store.

Authentication is OAuth 2.0 authorization-code + PKCE handled by
:mod:`memograph.sources.oauth.microsoft`. Tokens are loaded from the
encrypted store on each call and refreshed on-demand when expired,
matching :class:`memograph.sources.gdrive.GoogleDriveSource`.

Config shape (in ``SourceConfig.params``):

.. code-block:: json

    {
      "drive_id":  "b!....",          // optional; default: caller's personal drive
      "folder_id": "01...",           // optional; default: drive root
      "scopes":    ["Files.Read", "offline_access"],
      "sync_interval_seconds": 600
    }

Drive selection:
* ``personal`` (default — omit ``drive_id``) — the caller's OneDrive.
* ``b!...drive_id...`` — a specific drive id from the Graph
  ``/me/drives`` listing or ``/sites/{id}/drives``. Use this for
  SharePoint document libraries; the OneDrive site is just another
  drive in the same namespace.

Phase 4 ships read-only. ``write_document`` raises
:class:`SourceReadOnlyError` for symmetry with the Drive adapter.
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
    SourceNotFoundError,
    SourceReadOnlyError,
    SyncMode,
    SyncStats,
    WriteResult,
)
from memograph.sources.oauth.microsoft import (
    MicrosoftOAuthConfig,
    MicrosoftOAuthError,
    refresh_access_token,
)
from memograph.sources.oauth.token_store import (
    EncryptedTokenStore,
    TokenBundle,
    TokenStoreError,
)

logger = logging.getLogger(__name__)


GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Markdown MIME types we treat as direct downloads. Word documents
# arrive with ``application/vnd.openxmlformats-officedocument...`` and
# we don't try to convert them in Phase 4 — they're skipped during
# materialization. Plain markdown + text is what the vault stores.
ONEDRIVE_MARKDOWN_MIMETYPES = frozenset({
    "text/markdown",
    "text/x-markdown",
    "text/plain",
})


def _drive_prefix(drive_id: str | None) -> str:
    """Return the Graph URL prefix for ``me`` (personal) vs a specific drive."""
    if drive_id:
        return f"{GRAPH_BASE}/drives/{quote(drive_id, safe='')}"
    return f"{GRAPH_BASE}/me/drive"


class OneDriveSource(Source):
    """OneDrive / SharePoint as a read-only Markdown source."""

    def __init__(
        self,
        config: SourceConfig,
        *,
        token_store: EncryptedTokenStore | None = None,
        oauth_config: MicrosoftOAuthConfig | None = None,
        http_client_factory: Any = None,
    ) -> None:
        super().__init__(config)
        self._drive_id: str | None = config.params.get("drive_id") or None
        self._folder_id: str | None = config.params.get("folder_id") or None
        scopes = config.params.get("scopes")
        if scopes and isinstance(scopes, list):
            self._scopes: tuple[str, ...] = tuple(scopes)
        else:
            self._scopes = ()
        self._token_store: EncryptedTokenStore | None = token_store
        self._oauth_config: MicrosoftOAuthConfig | None = oauth_config
        self._http_client_factory = http_client_factory
        self._http: Any = None
        self._cached_token: TokenBundle | None = None

    # --- lazy plumbing ---

    def _ensure_oauth_config(self) -> MicrosoftOAuthConfig:
        if self._oauth_config is None:
            self._oauth_config = MicrosoftOAuthConfig.from_env()
            if self._scopes:
                self._oauth_config = MicrosoftOAuthConfig(
                    client_id=self._oauth_config.client_id,
                    client_secret=self._oauth_config.client_secret,
                    redirect_uri=self._oauth_config.redirect_uri,
                    tenant=self._oauth_config.tenant,
                    scopes=self._scopes,
                )
        return self._oauth_config

    def _ensure_token_store(self) -> EncryptedTokenStore:
        if self._token_store is None:
            raise SourceError(
                "OneDriveSource requires a token_store. The route "
                "layer constructs one rooted at the tenant's "
                "sources_dir; tests should inject a temp store."
            )
        return self._token_store

    def _ensure_http(self) -> Any:
        if self._http is not None:
            return self._http
        if self._http_client_factory is not None:
            self._http = self._http_client_factory()
            return self._http
        try:
            import httpx
        except ImportError as exc:
            raise SourceError(
                "OneDriveSource requires httpx. "
                "Install with: pip install 'memograph[sources-onedrive]'"
            ) from exc
        self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def _get_token(self) -> TokenBundle:
        store = self._ensure_token_store()
        try:
            bundle = store.load(self.source_id)
        except TokenStoreError as exc:
            raise SourceAuthError(str(exc)) from exc

        if not bundle.is_expired():
            return bundle

        if not bundle.refresh_token:
            raise SourceAuthError(
                f"OneDriveSource {self.source_id!r} has an expired "
                "access token and no refresh token; reconnect via the "
                "OAuth flow."
            )

        oauth = self._ensure_oauth_config()
        http = self._ensure_http()
        try:
            refreshed = await refresh_access_token(
                _HttpxAdapter(http),
                oauth,
                refresh_token=bundle.refresh_token,
            )
        except MicrosoftOAuthError as exc:
            raise SourceAuthError(f"OneDrive token refresh failed: {exc}") from exc
        store.save(self.source_id, refreshed)
        self._cached_token = refreshed
        return refreshed

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {"Authorization": f"{token.token_type} {token.access_token}"}

    # --- document ops ---

    async def list_documents(self) -> AsyncIterator[DocumentRef]:
        http = self._ensure_http()
        prefix = _drive_prefix(self._drive_id)
        if self._folder_id:
            initial = f"{prefix}/items/{quote(self._folder_id, safe='')}/children"
        else:
            initial = f"{prefix}/root/children"
        # Graph paginates via @odata.nextLink — a fully-qualified URL.
        # We follow it verbatim and break when it disappears.
        next_url: str | None = initial
        params: dict[str, str] | None = {
            "$select": "id,name,size,file,folder,lastModifiedDateTime,parentReference",
            "$top": "100",
        }
        while next_url:
            resp = await http.get(
                next_url,
                params=params,
                headers=await self._auth_headers(),
            )
            # Subsequent pages already have query params baked into nextLink.
            params = None
            if resp.status_code == 401:
                raise SourceAuthError(f"OneDrive list 401: {resp.text}")
            if resp.status_code != 200:
                raise SourceError(
                    f"OneDrive list failed ({resp.status_code}): {resp.text}"
                )
            data = resp.json()
            for item in data.get("value", []) or []:
                if "folder" in item:
                    # Phase 4 ships flat — folder recursion can come
                    # later if real users want a tree view. For now we
                    # take the top level of the configured folder.
                    continue
                file_info = item.get("file") or {}
                mime = file_info.get("mimeType", "")
                # Skip non-text items; we don't convert Word documents
                # in Phase 4.
                if mime and mime not in ONEDRIVE_MARKDOWN_MIMETYPES:
                    name_lower = item.get("name", "").lower()
                    if not (name_lower.endswith(".md") or name_lower.endswith(".txt")):
                        continue
                yield _ref_from_graph_item(item)
            next_url = data.get("@odata.nextLink")

    async def read_document(self, doc_id: str) -> Document:
        http = self._ensure_http()
        prefix = _drive_prefix(self._drive_id)
        meta_url = f"{prefix}/items/{quote(doc_id, safe='')}"
        meta_resp = await http.get(
            meta_url,
            params={"$select": "id,name,size,file,lastModifiedDateTime"},
            headers=await self._auth_headers(),
        )
        if meta_resp.status_code == 404:
            raise SourceNotFoundError(f"OneDrive item not found: {doc_id}")
        if meta_resp.status_code == 401:
            raise SourceAuthError(f"OneDrive metadata 401: {meta_resp.text}")
        if meta_resp.status_code != 200:
            raise SourceError(
                f"OneDrive metadata failed ({meta_resp.status_code}): "
                f"{meta_resp.text}"
            )
        meta = meta_resp.json()

        # The /content endpoint returns the raw bytes. Graph issues a
        # 302 to a short-lived pre-authenticated download URL; httpx
        # follows redirects by default so we receive the body in one call.
        body_resp = await http.get(
            f"{meta_url}/content",
            headers=await self._auth_headers(),
        )
        if body_resp.status_code == 401:
            raise SourceAuthError(f"OneDrive download 401: {body_resp.text}")
        if body_resp.status_code == 404:
            raise SourceNotFoundError(f"OneDrive content not found: {doc_id}")
        if body_resp.status_code != 200:
            raise SourceError(
                f"OneDrive download failed ({body_resp.status_code}): "
                f"{body_resp.text}"
            )
        try:
            content = body_resp.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceError(
                f"OneDrive file {doc_id} is not valid UTF-8 Markdown"
            ) from exc
        return Document(
            ref=_ref_from_graph_item(meta),
            content=content,
            encoding=DocumentEncoding.MARKDOWN,
        )

    async def write_document(self, doc: Document) -> WriteResult:
        raise SourceReadOnlyError(
            "OneDriveSource is read-only in Phase 4. Write-back via "
            "Graph upload session is planned for a later phase."
        )

    async def watch(self) -> AsyncIterator[ChangeEvent]:
        # Graph subscriptions need a webhook receiver with a valid
        # public URL and renewal scheduling — Phase 5 work. Until then
        # the SyncScheduler polls via list_documents.
        if False:  # pragma: no cover
            yield ChangeEvent.__new__(ChangeEvent)  # type: ignore[call-arg]
        return

    async def materialize_to_vault(self, vault_path: Path) -> SyncStats:
        started = perf_counter()
        vault = Path(vault_path).expanduser()
        vault.mkdir(parents=True, exist_ok=True)
        seen = written = 0
        async for ref in self.list_documents():
            seen += 1
            safe = _safe_filename(ref.title) or ref.doc_id
            name = f"{safe}.md" if not safe.lower().endswith((".md", ".txt")) else safe
            dst = vault / name
            if dst.exists() and datetime.fromtimestamp(
                dst.stat().st_mtime, tz=timezone.utc
            ) >= ref.modified_at:
                continue
            try:
                doc = await self.read_document(ref.doc_id)
            except SourceError as exc:
                logger.warning(
                    "skipping OneDrive item %s: %s", ref.doc_id, exc
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
        try:
            http = self._ensure_http()
            # /me is the cheapest authenticated probe — returns the
            # signed-in user's profile.
            resp = await http.get(
                f"{GRAPH_BASE}/me",
                params={"$select": "id,userPrincipalName"},
                headers=await self._auth_headers(),
            )
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
        except Exception as exc:  # noqa: BLE001
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )

        if resp.status_code != 200:
            status = (
                SourceHealthStatus.FAILED
                if resp.status_code in {401, 403}
                else SourceHealthStatus.DEGRADED
            )
            return SourceHealth(
                status=status,
                checked_at=datetime.now(timezone.utc),
                last_error=f"Graph /me returned {resp.status_code}",
            )
        return SourceHealth(
            status=SourceHealthStatus.OK,
            checked_at=datetime.now(timezone.utc),
            last_successful_sync_at=datetime.now(timezone.utc),
        )

    @property
    def supports_writes(self) -> bool:
        return False

    @property
    def supports_watch(self) -> bool:
        return False


# --- helpers ---


class _HttpxAdapter:
    """Adapt ``httpx.AsyncClient`` to the OAuth module's Protocol."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def post(self, url: str, data: dict[str, str]) -> Any:
        return await self._client.post(url, data=data)


def _ref_from_graph_item(item: dict[str, Any]) -> DocumentRef:
    modified_raw = item.get("lastModifiedDateTime", "")
    try:
        modified = (
            datetime.fromisoformat(modified_raw.replace("Z", "+00:00"))
            if modified_raw
            else datetime.now(timezone.utc)
        )
    except (ValueError, AttributeError):
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
        metadata={
            "mime_type": file_info.get("mimeType"),
            "hash_quick_xor": (file_info.get("hashes") or {}).get("quickXorHash"),
        },
    )


def _safe_filename(title: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in title)
    cleaned = cleaned.strip(" .")
    return cleaned[:120]


__all__ = ["OneDriveSource"]
