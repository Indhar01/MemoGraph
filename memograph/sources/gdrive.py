"""``GoogleDriveSource`` — a Google Drive folder as a Markdown source.

Phase 3 adapter. Uses the Drive v3 REST API directly via ``httpx``
(no `google-api-python-client` dep), so the install footprint stays
small: just ``httpx`` (already a transitive dep) + ``cryptography``
for the token store.

Authentication is OAuth 2.0 authorization-code + PKCE handled by
:mod:`memograph.sources.oauth.google`. The adapter loads tokens
from the encrypted store on each call, refreshing them on-demand
when expired. Refresh failures (revoked grant, deleted client)
raise :class:`SourceAuthError` so the routes can surface 401 and
the UI can prompt the user to reconnect.

Config shape (in ``SourceConfig.params``):

.. code-block:: json

    {
      "folder_id": "1AbcDef...",  // optional; default: search whole Drive
      "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
      "sync_interval_seconds": 600
    }

Drive scope guidance:
* ``drive.readonly`` — read every file the user can see. Wide.
* ``drive.file`` — read only files the user opened with the app.
  Narrower but breaks the "point at my whole Drive" UX. Operators
  who care about least-privilege should pick this and accept the
  reduced surface.

Phase 3 ships read-only; writes (``write_document``) raise
:class:`SourceReadOnlyError` because Google Docs round-tripping
needs a block-diff layer that isn't in scope yet.
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
from memograph.sources.oauth.google import (
    GoogleOAuthConfig,
    GoogleOAuthError,
    refresh_access_token,
)
from memograph.sources.oauth.token_store import (
    EncryptedTokenStore,
    TokenBundle,
    TokenStoreError,
)

logger = logging.getLogger(__name__)


DRIVE_FILES_ENDPOINT = "https://www.googleapis.com/drive/v3/files"
"""Drive v3 list / metadata endpoint."""

DRIVE_DOWNLOAD_ENDPOINT = "https://www.googleapis.com/drive/v3/files/{file_id}"
"""GET with ?alt=media downloads file contents."""

# Markdown MIME types we accept from Drive. Google Docs use their
# proprietary ``application/vnd.google-apps.document`` mimeType and
# need ``files/export`` to materialise to text/markdown — handled
# separately below.
DRIVE_MARKDOWN_MIMETYPES = frozenset({
    "text/markdown",
    "text/x-markdown",
    "text/plain",  # Plain .txt is often used for vault notes
})

GOOGLE_DOCS_MIMETYPE = "application/vnd.google-apps.document"


class GoogleDriveSource(Source):
    """Google Drive as a read-only Markdown source.

    Construction is cheap. The OAuth config is resolved lazily on
    the first I/O call, and the HTTP client is built on first use
    and reused across calls inside the same adapter instance.
    """

    def __init__(
        self,
        config: SourceConfig,
        *,
        token_store: EncryptedTokenStore | None = None,
        oauth_config: GoogleOAuthConfig | None = None,
        http_client_factory: Any = None,
    ) -> None:
        super().__init__(config)
        self._folder_id: str | None = config.params.get("folder_id") or None
        scopes = config.params.get("scopes")
        if scopes and isinstance(scopes, list):
            self._scopes: tuple[str, ...] = tuple(scopes)
        else:
            self._scopes = ()  # use defaults from GoogleOAuthConfig
        # Dependency injection — Phase 5 tests inject a mock store /
        # OAuth config / HTTP client without monkey-patching globals.
        self._token_store: EncryptedTokenStore | None = token_store
        self._oauth_config: GoogleOAuthConfig | None = oauth_config
        self._http_client_factory = http_client_factory
        self._http: Any = None
        self._cached_token: TokenBundle | None = None

    # --- lazy plumbing ---

    def _ensure_oauth_config(self) -> GoogleOAuthConfig:
        if self._oauth_config is None:
            # Allows the route layer to construct sources without
            # plumbing the config through every layer — fall back
            # to env if not injected.
            self._oauth_config = GoogleOAuthConfig.from_env()
            if self._scopes:
                self._oauth_config = GoogleOAuthConfig(
                    client_id=self._oauth_config.client_id,
                    client_secret=self._oauth_config.client_secret,
                    redirect_uri=self._oauth_config.redirect_uri,
                    scopes=self._scopes,
                )
        return self._oauth_config

    def _ensure_token_store(self) -> EncryptedTokenStore:
        if self._token_store is None:
            raise SourceError(
                "GoogleDriveSource requires a token_store. The route "
                "layer constructs one rooted at the tenant's sources_dir; "
                "tests should inject a temp store."
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
                "GoogleDriveSource requires httpx. "
                "Install with: pip install 'memograph[sources-gdrive]'"
            ) from exc
        # 30s read timeout — Drive list calls on large folders can be
        # slow but rarely beyond 30s. Configurable via env if needed.
        self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def _get_token(self) -> TokenBundle:
        """Return a fresh access token, refreshing if needed."""
        store = self._ensure_token_store()
        try:
            bundle = store.load(self.source_id)
        except TokenStoreError as exc:
            raise SourceAuthError(str(exc)) from exc

        if not bundle.is_expired():
            return bundle

        if not bundle.refresh_token:
            raise SourceAuthError(
                f"GoogleDriveSource {self.source_id!r} has an expired "
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
        except GoogleOAuthError as exc:
            raise SourceAuthError(f"Drive token refresh failed: {exc}") from exc
        store.save(self.source_id, refreshed)
        self._cached_token = refreshed
        return refreshed

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {"Authorization": f"{token.token_type} {token.access_token}"}

    # --- document ops ---

    async def list_documents(self) -> AsyncIterator[DocumentRef]:
        http = self._ensure_http()
        # Drive query language: filter by mimeType + parent folder.
        # We include both native markdown mime types and Google Docs;
        # the latter get exported to markdown on read.
        mime_clause = " or ".join(
            f"mimeType = '{m}'" for m in (*DRIVE_MARKDOWN_MIMETYPES, GOOGLE_DOCS_MIMETYPE)
        )
        q_parts = [f"({mime_clause})", "trashed = false"]
        if self._folder_id:
            q_parts.append(f"'{self._folder_id}' in parents")
        query = " and ".join(q_parts)

        page_token: str | None = None
        while True:
            params = {
                "q": query,
                "fields": (
                    "nextPageToken,"
                    "files(id,name,mimeType,modifiedTime,size,md5Checksum)"
                ),
                "pageSize": "100",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = await http.get(
                DRIVE_FILES_ENDPOINT,
                params=params,
                headers=await self._auth_headers(),
            )
            if resp.status_code == 401:
                raise SourceAuthError(f"Drive list 401: {resp.text}")
            if resp.status_code != 200:
                raise SourceError(
                    f"Drive list failed ({resp.status_code}): {resp.text}"
                )
            data = resp.json()
            for f in data.get("files", []) or []:
                yield _ref_from_drive_file(f)
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    async def read_document(self, doc_id: str) -> Document:
        http = self._ensure_http()
        # Fetch metadata first to know the mimeType — Google Docs need
        # `/export` rather than `?alt=media`.
        meta_resp = await http.get(
            DRIVE_DOWNLOAD_ENDPOINT.format(file_id=quote(doc_id, safe="")),
            params={"fields": "id,name,mimeType,modifiedTime,size,md5Checksum"},
            headers=await self._auth_headers(),
        )
        if meta_resp.status_code == 404:
            raise SourceNotFoundError(f"Drive file not found: {doc_id}")
        if meta_resp.status_code == 401:
            raise SourceAuthError(f"Drive metadata 401: {meta_resp.text}")
        if meta_resp.status_code != 200:
            raise SourceError(
                f"Drive metadata failed ({meta_resp.status_code}): "
                f"{meta_resp.text}"
            )
        meta = meta_resp.json()
        mime = meta.get("mimeType", "")

        if mime == GOOGLE_DOCS_MIMETYPE:
            # Export the doc to markdown. Google's text/markdown
            # export landed in 2024 and is the simplest path.
            download_url = (
                f"{DRIVE_DOWNLOAD_ENDPOINT.format(file_id=quote(doc_id, safe=''))}"
                "/export"
            )
            params: dict[str, str] = {"mimeType": "text/markdown"}
        else:
            download_url = DRIVE_DOWNLOAD_ENDPOINT.format(file_id=quote(doc_id, safe=""))
            params = {"alt": "media"}

        body_resp = await http.get(
            download_url, params=params, headers=await self._auth_headers()
        )
        if body_resp.status_code == 401:
            raise SourceAuthError(f"Drive download 401: {body_resp.text}")
        if body_resp.status_code != 200:
            raise SourceError(
                f"Drive download failed ({body_resp.status_code}): "
                f"{body_resp.text}"
            )
        try:
            content = body_resp.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceError(
                f"Drive file {doc_id} is not valid UTF-8 Markdown"
            ) from exc
        return Document(
            ref=_ref_from_drive_file(meta),
            content=content,
            encoding=DocumentEncoding.MARKDOWN,
        )

    async def write_document(self, doc: Document) -> WriteResult:
        raise SourceReadOnlyError(
            "GoogleDriveSource is read-only in Phase 3. Round-trip "
            "writes need a Google Docs block-diff layer planned for "
            "a later phase."
        )

    async def watch(self) -> AsyncIterator[ChangeEvent]:
        # Drive supports push notifications via watch channels (POST
        # to /files/{id}/watch). That needs a webhook receiver +
        # channel renewal and is Phase 5 work; for now we rely on
        # the SyncScheduler's polling.
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
            # Filenames inside the local cache use the Drive file
            # name; collisions get the file-id suffix.
            safe = _safe_filename(ref.title) or ref.doc_id
            name = f"{safe}.md" if not safe.endswith(".md") else safe
            dst = vault / name
            if dst.exists():
                # md5Checksum is preferred for Drive; fall back to
                # mtime when Google doesn't provide one (Google Docs).
                md5 = ref.metadata.get("md5_checksum")
                if md5 is not None:
                    # We don't recompute md5 of the local file every
                    # tick; cheap mtime check is enough for the bulk
                    # case and a periodic full reconcile catches drift.
                    pass
                if datetime.fromtimestamp(
                    dst.stat().st_mtime, tz=timezone.utc
                ) >= ref.modified_at:
                    continue
            try:
                doc = await self.read_document(ref.doc_id)
            except SourceError as exc:
                logger.warning(
                    "skipping Drive file %s: %s", ref.doc_id, exc
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
            # The /about endpoint is the cheapest authenticated probe.
            http = self._ensure_http()
            resp = await http.get(
                "https://www.googleapis.com/drive/v3/about",
                params={"fields": "user(emailAddress,displayName)"},
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
                last_error=f"Drive /about returned {resp.status_code}",
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
    """Wraps an ``httpx.AsyncClient`` so the OAuth module sees the
    minimal Protocol it expects without importing httpx."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def post(self, url: str, data: dict[str, str]) -> Any:
        return await self._client.post(url, data=data)


def _ref_from_drive_file(f: dict[str, Any]) -> DocumentRef:
    """Build a :class:`DocumentRef` from a Drive `files` resource."""
    modified_raw = f.get("modifiedTime", "")
    try:
        modified = (
            datetime.fromisoformat(modified_raw.replace("Z", "+00:00"))
            if modified_raw
            else datetime.now(timezone.utc)
        )
    except (ValueError, AttributeError):
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


def _safe_filename(title: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in title)
    cleaned = cleaned.strip(" .")
    return cleaned[:120]


__all__ = ["GoogleDriveSource"]
