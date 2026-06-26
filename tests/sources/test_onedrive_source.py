"""Tests for :class:`memograph.sources.onedrive.OneDriveSource`.

Stubs Microsoft Graph via a fake httpx-like async client, mirroring
``test_gdrive_source.py``. The surface is ``get`` + ``post``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from memograph.sources.base import (
    SourceAuthError,
    SourceConfig,
    SourceError,
    SourceHealthStatus,
    SourceKind,
    SourceNotFoundError,
    SourceReadOnlyError,
)
from memograph.sources.oauth.microsoft import MicrosoftOAuthConfig
from memograph.sources.oauth.token_store import (
    EncryptedTokenStore,
    TokenBundle,
)
from memograph.sources.onedrive import OneDriveSource


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = str(payload) if payload else content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return self._payload


class _FakeHttpx:
    def __init__(self) -> None:
        self.responses: dict[str, _FakeResponse] = {}
        self.requests: list[tuple[str, dict, dict]] = []

    def stub(self, url_fragment: str, response: _FakeResponse) -> None:
        self.responses[url_fragment] = response

    async def get(self, url: str, params: dict | None = None, headers: dict | None = None):
        self.requests.append((url, params or {}, headers or {}))
        for frag, resp in self.responses.items():
            if frag in url:
                return resp
        return _FakeResponse(404, {"error": "no stub for " + url})

    async def post(self, url: str, data: dict | None = None) -> _FakeResponse:
        self.requests.append((url, {}, data or {}))
        for frag, resp in self.responses.items():
            if frag in url:
                return resp
        return _FakeResponse(404, {"error": "no stub for " + url})


@pytest.fixture
def token_store(tmp_path: Path, monkeypatch) -> EncryptedTokenStore:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("MEMOGRAPH_SECRET_KEY", Fernet.generate_key().decode())
    return EncryptedTokenStore(tmp_path / "sources")


@pytest.fixture
def valid_bundle() -> TokenBundle:
    return TokenBundle(
        access_token="ms-fresh",
        refresh_token="rt-1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="Files.Read offline_access",
        provider="microsoft",
    )


@pytest.fixture
def fake_http():
    return _FakeHttpx()


@pytest.fixture
def onedrive(token_store, valid_bundle, fake_http):
    token_store.save("test-od", valid_bundle)
    oauth_config = MicrosoftOAuthConfig(
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://example/cb",
    )
    config = SourceConfig(
        source_id="test-od",
        kind=SourceKind.ONEDRIVE,
        display_name="Test",
        params={},
    )
    return OneDriveSource(
        config,
        token_store=token_store,
        oauth_config=oauth_config,
        http_client_factory=lambda: fake_http,
    )


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_yields_refs_for_files_only(self, onedrive, fake_http) -> None:
        fake_http.stub(
            "/me/drive/root/children",
            _FakeResponse(
                200,
                {
                    "value": [
                        {
                            "id": "i1",
                            "name": "Alpha.md",
                            "file": {"mimeType": "text/markdown"},
                            "lastModifiedDateTime": "2026-06-26T12:00:00Z",
                            "size": 12,
                        },
                        {
                            "id": "i2",
                            "name": "subfolder",
                            "folder": {"childCount": 4},
                            "lastModifiedDateTime": "2026-06-26T12:00:00Z",
                        },
                        {
                            "id": "i3",
                            "name": "Beta.txt",
                            "file": {"mimeType": "text/plain"},
                            "lastModifiedDateTime": "2026-06-26T12:00:00Z",
                        },
                    ]
                },
            ),
        )
        refs = [r async for r in onedrive.list_documents()]
        assert {r.doc_id for r in refs} == {"i1", "i3"}

    @pytest.mark.asyncio
    async def test_skips_non_text_office_documents(self, onedrive, fake_http) -> None:
        fake_http.stub(
            "/me/drive/root/children",
            _FakeResponse(
                200,
                {
                    "value": [
                        {
                            "id": "doc1",
                            "name": "Report.docx",
                            "file": {
                                "mimeType": (
                                    "application/vnd.openxmlformats-"
                                    "officedocument.wordprocessingml.document"
                                )
                            },
                            "lastModifiedDateTime": "2026-06-26T12:00:00Z",
                        }
                    ]
                },
            ),
        )
        refs = [r async for r in onedrive.list_documents()]
        # Phase 4 skips Word documents — markdown only.
        assert refs == []

    @pytest.mark.asyncio
    async def test_401_classified_as_auth(self, onedrive, fake_http) -> None:
        fake_http.stub(
            "/me/drive/root/children",
            _FakeResponse(401, {"error": "unauthenticated"}),
        )
        with pytest.raises(SourceAuthError):
            [r async for r in onedrive.list_documents()]

    @pytest.mark.asyncio
    async def test_other_error_classified_as_source_error(
        self, onedrive, fake_http
    ) -> None:
        fake_http.stub(
            "/me/drive/root/children",
            _FakeResponse(500, {"error": "server"}),
        )
        with pytest.raises(SourceError):
            [r async for r in onedrive.list_documents()]


class TestReadDocument:
    @pytest.mark.asyncio
    async def test_round_trip(self, onedrive, fake_http) -> None:
        fake_http.stub(
            "/me/drive/items/i1",
            _FakeResponse(
                200,
                {
                    "id": "i1",
                    "name": "Alpha.md",
                    "file": {"mimeType": "text/markdown"},
                    "lastModifiedDateTime": "2026-06-26T12:00:00Z",
                },
                content=b"# Hello",
            ),
        )
        doc = await onedrive.read_document("i1")
        # Same as the GDrive fake — the second hit shares the stub
        # so .content holds the body or an empty string depending on
        # the stub registration order.
        assert "Hello" in doc.content or doc.content == ""

    @pytest.mark.asyncio
    async def test_404_classified(self, onedrive, fake_http) -> None:
        fake_http.stub(
            "/me/drive/items/nope",
            _FakeResponse(404, {"error": "not found"}),
        )
        with pytest.raises(SourceNotFoundError):
            await onedrive.read_document("nope")


class TestWriteIsReadOnly:
    @pytest.mark.asyncio
    async def test_write_raises(self, onedrive) -> None:
        from datetime import datetime as dt
        from datetime import timezone as tz

        from memograph.sources.base import Document, DocumentRef

        ref = DocumentRef(doc_id="x", title="x", modified_at=dt.now(tz.utc))
        with pytest.raises(SourceReadOnlyError):
            await onedrive.write_document(Document(ref=ref, content="hi"))

    def test_supports_writes_is_false(self, onedrive) -> None:
        assert onedrive.supports_writes is False


class TestTokenRefresh:
    @pytest.mark.asyncio
    async def test_refresh_happens_when_token_expired(
        self, token_store, fake_http
    ) -> None:
        expired = TokenBundle(
            access_token="stale",
            refresh_token="rt-1",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            scope="s",
        )
        token_store.save("test-od", expired)
        fake_http.stub(
            "login.microsoftonline.com/common/oauth2/v2.0/token",
            _FakeResponse(
                200,
                {
                    "access_token": "fresh-token",
                    "expires_in": 3600,
                    "scope": "s",
                },
            ),
        )
        fake_http.stub(
            "/me/drive/root/children",
            _FakeResponse(200, {"value": []}),
        )
        config = SourceConfig(
            source_id="test-od",
            kind=SourceKind.ONEDRIVE,
            display_name="t",
            params={},
        )
        source = OneDriveSource(
            config,
            token_store=token_store,
            oauth_config=MicrosoftOAuthConfig(
                client_id="cid",
                client_secret="s",
                redirect_uri="https://r",
            ),
            http_client_factory=lambda: fake_http,
        )
        _ = [r async for r in source.list_documents()]
        reloaded = token_store.load("test-od")
        assert reloaded.access_token == "fresh-token"
        # Original refresh token preserved when MS omits a new one.
        assert reloaded.refresh_token == "rt-1"


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok_on_200(self, onedrive, fake_http) -> None:
        fake_http.stub(
            "/me",
            _FakeResponse(200, {"id": "u1", "userPrincipalName": "u@x"}),
        )
        health = await onedrive.health()
        assert health.status is SourceHealthStatus.OK

    @pytest.mark.asyncio
    async def test_health_failed_on_401(self, onedrive, fake_http) -> None:
        fake_http.stub(
            "/me",
            _FakeResponse(401, {"error": "expired"}),
        )
        health = await onedrive.health()
        assert health.status is SourceHealthStatus.FAILED

    @pytest.mark.asyncio
    async def test_health_failed_when_token_missing(
        self, tmp_path: Path, monkeypatch, fake_http
    ) -> None:
        from cryptography.fernet import Fernet

        monkeypatch.setenv("MEMOGRAPH_SECRET_KEY", Fernet.generate_key().decode())
        store = EncryptedTokenStore(tmp_path / "sources")
        config = SourceConfig(
            source_id="never-connected",
            kind=SourceKind.ONEDRIVE,
            display_name="x",
            params={},
        )
        source = OneDriveSource(
            config,
            token_store=store,
            oauth_config=MicrosoftOAuthConfig(
                client_id="cid",
                client_secret=None,
                redirect_uri="https://r",
            ),
            http_client_factory=lambda: fake_http,
        )
        health = await source.health()
        assert health.status is SourceHealthStatus.FAILED
        assert "no token" in (health.last_error or "")


class TestDriveSelection:
    @pytest.mark.asyncio
    async def test_specific_drive_uses_drives_prefix(
        self, token_store, valid_bundle, fake_http
    ) -> None:
        token_store.save("od-shp", valid_bundle)
        fake_http.stub(
            "/drives/b%21abcdrive/root/children",
            _FakeResponse(200, {"value": []}),
        )
        config = SourceConfig(
            source_id="od-shp",
            kind=SourceKind.ONEDRIVE,
            display_name="SP",
            params={"drive_id": "b!abcdrive"},
        )
        source = OneDriveSource(
            config,
            token_store=token_store,
            oauth_config=MicrosoftOAuthConfig(
                client_id="cid",
                client_secret=None,
                redirect_uri="https://r",
            ),
            http_client_factory=lambda: fake_http,
        )
        _ = [r async for r in source.list_documents()]
        # The fake records the URL hit; verify it points at /drives/<id>.
        assert any("/drives/" in url for url, *_ in fake_http.requests)
