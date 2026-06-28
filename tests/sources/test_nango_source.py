"""Tests for the unified :class:`NangoBackedSource` adapter.

Covers the three OAuth cloud kinds (GDRIVE, ONEDRIVE, NOTION) through
the same fake-httpx pattern used elsewhere. Provider-specific quirks
(Google Docs export, OneDrive drives vs personal, Notion blocks→md)
get one test each.
"""

from __future__ import annotations

from typing import Any

import pytest

from memograph.sources.base import (
    Document,
    DocumentRef,
    SourceAuthError,
    SourceConfig,
    SourceHealthStatus,
    SourceKind,
    SourceReadOnlyError,
)
from memograph.sources.nango_client import NangoClient, NangoConfig
from memograph.sources.nango_source import NangoBackedSource


# Minimal fake httpx shared with the adapter — same shape as the one
# in test_nango_client.py. Inlined here because tests/ is not a package.
class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        content: bytes = b"",
        text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = (
            text
            if text is not None
            else (
                str(payload) if payload else content.decode("utf-8", errors="replace")
            )
        )

    def json(self) -> Any:
        return self._payload


class _FakeHttpx:
    def __init__(self) -> None:
        self.responses: dict[tuple[str, str], _FakeResponse] = {}
        self.calls: list[dict[str, Any]] = []

    def stub(self, method: str, fragment: str, response: _FakeResponse) -> None:
        self.responses[(method.upper(), fragment)] = response

    def _lookup(self, method: str, url: str) -> _FakeResponse:
        for (m, frag), resp in self.responses.items():
            if m == method.upper() and frag in url:
                return resp
        return _FakeResponse(404, {"error": "no stub for " + method + " " + url})

    async def get(self, url, params=None, headers=None):
        self.calls.append(
            {"method": "GET", "url": url, "params": params, "headers": headers}
        )
        return self._lookup("GET", url)

    async def post(self, url, json=None, params=None, headers=None):
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "json": json,
                "params": params,
                "headers": headers,
            }
        )
        return self._lookup("POST", url)

    async def delete(self, url, params=None):
        self.calls.append({"method": "DELETE", "url": url, "params": params})
        return self._lookup("DELETE", url)

    async def aclose(self):
        return None


@pytest.fixture
def fake_http() -> _FakeHttpx:
    return _FakeHttpx()


@pytest.fixture
def nango_client(fake_http) -> NangoClient:
    return NangoClient(
        NangoConfig(base_url="http://nango", secret_key="sk", webhook_secret="wh"),
        http_client=fake_http,
    )


def _config(kind: SourceKind, **params: Any) -> SourceConfig:
    return SourceConfig(
        source_id=f"{kind.value}-test",
        kind=kind,
        display_name=kind.value,
        params={"nango_connection_id": "conn-1", **params},
    )


# --- construction --------------------------------------------------------


class TestConstruction:
    def test_unknown_kind_refused(self, nango_client) -> None:
        from memograph.sources.base import SourceError

        cfg = SourceConfig(
            source_id="x",
            kind=SourceKind.LOCAL,  # not an OAuth kind
            display_name="x",
            params={"nango_connection_id": "c"},
        )
        with pytest.raises(SourceError, match="cannot serve kind"):
            NangoBackedSource(cfg, nango_client=nango_client)

    def test_missing_connection_id_refused(self, nango_client) -> None:
        from memograph.sources.base import SourceError

        cfg = SourceConfig(
            source_id="x",
            kind=SourceKind.GDRIVE,
            display_name="x",
            params={},
        )
        with pytest.raises(SourceError, match="nango_connection_id"):
            NangoBackedSource(cfg, nango_client=nango_client)


# --- Drive ----------------------------------------------------------------


class TestDrive:
    @pytest.mark.asyncio
    async def test_list_yields_refs(self, nango_client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/proxy/drive/v3/files",
            _FakeResponse(
                200,
                {
                    "files": [
                        {
                            "id": "f1",
                            "name": "Alpha.md",
                            "mimeType": "text/markdown",
                            "modifiedTime": "2026-06-26T12:00:00Z",
                            "size": "12",
                        },
                        {
                            "id": "f2",
                            "name": "Doc",
                            "mimeType": "application/vnd.google-apps.document",
                            "modifiedTime": "2026-06-26T12:00:00Z",
                        },
                    ]
                },
            ),
        )
        source = NangoBackedSource(
            _config(SourceKind.GDRIVE), nango_client=nango_client
        )
        refs = [r async for r in source.list_documents()]
        assert {r.doc_id for r in refs} == {"f1", "f2"}

    @pytest.mark.asyncio
    async def test_read_google_doc_uses_export(self, nango_client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/proxy/drive/v3/files/g1",
            _FakeResponse(
                200,
                {
                    "id": "g1",
                    "name": "G",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2026-06-26T12:00:00Z",
                },
                content=b"# Exported",
            ),
        )
        # The export call shares the same fragment-based stub.
        source = NangoBackedSource(
            _config(SourceKind.GDRIVE), nango_client=nango_client
        )
        doc = await source.read_document("g1")
        # The fake serves the same response on both metadata and export
        # paths; what matters is that the second call hit the export
        # endpoint with mimeType=text/markdown.
        assert any(
            "/export" in c["url"] for c in fake_http.calls
        ), "expected /export to be called for a Google Doc"
        assert isinstance(doc, Document)

    @pytest.mark.asyncio
    async def test_read_401_is_auth_error(self, nango_client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/proxy/drive/v3/files/x",
            _FakeResponse(401, {"error": "expired"}, text="expired"),
        )
        source = NangoBackedSource(
            _config(SourceKind.GDRIVE), nango_client=nango_client
        )
        with pytest.raises(SourceAuthError):
            await source.read_document("x")


# --- OneDrive -------------------------------------------------------------


class TestOneDrive:
    @pytest.mark.asyncio
    async def test_list_filters_office_documents(self, nango_client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/proxy/me/drive/root/children",
            _FakeResponse(
                200,
                {
                    "value": [
                        {
                            "id": "i1",
                            "name": "Alpha.md",
                            "file": {"mimeType": "text/markdown"},
                            "lastModifiedDateTime": "2026-06-26T12:00:00Z",
                        },
                        {
                            "id": "i2",
                            "name": "Report.docx",
                            "file": {
                                "mimeType": (
                                    "application/vnd.openxmlformats-"
                                    "officedocument.wordprocessingml.document"
                                )
                            },
                            "lastModifiedDateTime": "2026-06-26T12:00:00Z",
                        },
                        {"id": "i3", "name": "folder", "folder": {}},
                    ]
                },
            ),
        )
        source = NangoBackedSource(
            _config(SourceKind.ONEDRIVE), nango_client=nango_client
        )
        refs = [r async for r in source.list_documents()]
        # Folders + Word documents excluded; only markdown remains.
        assert [r.doc_id for r in refs] == ["i1"]

    @pytest.mark.asyncio
    async def test_drive_id_routes_to_drives_path(
        self, nango_client, fake_http
    ) -> None:
        fake_http.stub(
            "GET",
            "/proxy/drives/b%21drv/root/children",
            _FakeResponse(200, {"value": []}),
        )
        source = NangoBackedSource(
            _config(SourceKind.ONEDRIVE, drive_id="b!drv"),
            nango_client=nango_client,
        )
        _ = [r async for r in source.list_documents()]
        assert any("/proxy/drives/" in c["url"] for c in fake_http.calls)


# --- Notion ---------------------------------------------------------------


class TestNotion:
    @pytest.mark.asyncio
    async def test_list_without_database_id_uses_search(
        self, nango_client, fake_http
    ) -> None:
        """Sources without database_id fall back to /v1/search."""
        fake_http.stub(
            "POST",
            "/proxy/v1/search",
            _FakeResponse(
                200,
                {
                    "results": [
                        {
                            "object": "page",
                            "id": "page-1",
                            "last_edited_time": "2026-06-26T12:00:00Z",
                            "properties": {
                                "Name": {
                                    "type": "title",
                                    "title": [{"plain_text": "Hello"}],
                                }
                            },
                            "url": "https://notion.so/page-1",
                        }
                    ],
                    "has_more": False,
                },
            ),
        )
        source = NangoBackedSource(
            _config(SourceKind.NOTION), nango_client=nango_client
        )
        refs = [r async for r in source.list_documents()]
        assert len(refs) == 1
        assert refs[0].doc_id == "page-1"

    @pytest.mark.asyncio
    async def test_list_pages_from_database_query(
        self, nango_client, fake_http
    ) -> None:
        fake_http.stub(
            "POST",
            "/proxy/v1/databases/db-1/query",
            _FakeResponse(
                200,
                {
                    "results": [
                        {
                            "id": "page-1",
                            "last_edited_time": "2026-06-26T12:00:00Z",
                            "properties": {
                                "Name": {
                                    "type": "title",
                                    "title": [{"plain_text": "Hello"}],
                                }
                            },
                            "url": "https://notion.so/page-1",
                        }
                    ],
                    "has_more": False,
                },
            ),
        )
        source = NangoBackedSource(
            _config(SourceKind.NOTION, database_id="db-1"),
            nango_client=nango_client,
        )
        refs = [r async for r in source.list_documents()]
        assert len(refs) == 1
        assert refs[0].doc_id == "page-1"
        assert refs[0].title == "Hello"

    @pytest.mark.asyncio
    async def test_read_renders_blocks_to_markdown(
        self, nango_client, fake_http
    ) -> None:
        fake_http.stub(
            "GET",
            "/proxy/v1/pages/page-1",
            _FakeResponse(
                200,
                {
                    "id": "page-1",
                    "last_edited_time": "2026-06-26T12:00:00Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"plain_text": "Hello"}],
                        }
                    },
                },
            ),
        )
        fake_http.stub(
            "GET",
            "/proxy/v1/blocks/page-1/children",
            _FakeResponse(
                200,
                {
                    "results": [
                        {
                            "type": "heading_1",
                            "heading_1": {"rich_text": [{"plain_text": "Title"}]},
                        },
                        {
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"plain_text": "Hello, world."}]
                            },
                        },
                    ],
                    "has_more": False,
                },
            ),
        )
        source = NangoBackedSource(
            _config(SourceKind.NOTION, database_id="db-1"),
            nango_client=nango_client,
        )
        doc = await source.read_document("page-1")
        assert "# Title" in doc.content
        assert "Hello, world." in doc.content


# --- write + health ------------------------------------------------------


class TestWriteIsReadOnly:
    @pytest.mark.asyncio
    async def test_write_raises(self, nango_client) -> None:
        from datetime import datetime, timezone

        source = NangoBackedSource(
            _config(SourceKind.GDRIVE), nango_client=nango_client
        )
        ref = DocumentRef(doc_id="x", title="x", modified_at=datetime.now(timezone.utc))
        with pytest.raises(SourceReadOnlyError):
            await source.write_document(Document(ref=ref, content="hi"))


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self, nango_client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/connections/conn-1",
            _FakeResponse(
                200,
                {
                    "connection_id": "conn-1",
                    "provider_config_key": "google-drive",
                    "provider": "google-drive",
                    "errors": [],
                    "metadata": {},
                    "created_at": None,
                    "updated_at": None,
                },
            ),
        )
        source = NangoBackedSource(
            _config(SourceKind.GDRIVE), nango_client=nango_client
        )
        health = await source.health()
        assert health.status is SourceHealthStatus.OK

    @pytest.mark.asyncio
    async def test_health_failed_on_auth_error(self, nango_client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/connections/conn-1",
            _FakeResponse(424, {"error": "expired"}),
        )
        source = NangoBackedSource(
            _config(SourceKind.GDRIVE), nango_client=nango_client
        )
        health = await source.health()
        assert health.status is SourceHealthStatus.FAILED
        assert "refreshed" in (health.last_error or "")
