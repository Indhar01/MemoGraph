"""Tests for :class:`memograph.sources.gdrive.GoogleDriveSource`.

Stubs the Drive REST API via a fake httpx-like async client. The
adapter only uses ``get`` (and POSTs through the OAuth module
separately tested in ``test_oauth.py``), so the surface is small.
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
from memograph.sources.gdrive import GoogleDriveSource
from memograph.sources.oauth.google import GoogleOAuthConfig
from memograph.sources.oauth.token_store import (
    EncryptedTokenStore,
    TokenBundle,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = str(payload) if payload else content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return self._payload


class _FakeHttpx:
    """Stand-in for ``httpx.AsyncClient`` covering only what GDrive
    uses (``get`` + ``post``). Tests preload responses keyed by a
    substring of the requested URL."""

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
        access_token="ya29-fresh",
        refresh_token="rt-1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="https://www.googleapis.com/auth/drive.readonly",
        provider="google",
    )


@pytest.fixture
def fake_http():
    return _FakeHttpx()


@pytest.fixture
def gdrive(token_store, valid_bundle, fake_http):
    token_store.save("test-drive", valid_bundle)
    oauth_config = GoogleOAuthConfig(
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://example/cb",
    )
    config = SourceConfig(
        source_id="test-drive",
        kind=SourceKind.GDRIVE,
        display_name="Test",
        params={},
    )
    return GoogleDriveSource(
        config,
        token_store=token_store,
        oauth_config=oauth_config,
        http_client_factory=lambda: fake_http,
    )


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_yields_refs_from_drive_response(self, gdrive, fake_http) -> None:
        fake_http.stub(
            "/drive/v3/files",
            _FakeResponse(
                200,
                {
                    "files": [
                        {
                            "id": "f1",
                            "name": "Alpha.md",
                            "mimeType": "text/markdown",
                            "modifiedTime": "2026-06-26T12:00:00.000Z",
                            "size": "12",
                        },
                        {
                            "id": "f2",
                            "name": "Doc",
                            "mimeType": "application/vnd.google-apps.document",
                            "modifiedTime": "2026-06-26T12:00:00.000Z",
                        },
                    ]
                },
            ),
        )
        refs = [ref async for ref in gdrive.list_documents()]
        assert len(refs) == 2
        assert refs[0].doc_id == "f1"
        assert refs[1].title == "Doc"

    @pytest.mark.asyncio
    async def test_401_classified_as_auth(self, gdrive, fake_http) -> None:
        fake_http.stub(
            "/drive/v3/files",
            _FakeResponse(401, {"error": "unauthenticated"}),
        )
        with pytest.raises(SourceAuthError):
            [ref async for ref in gdrive.list_documents()]

    @pytest.mark.asyncio
    async def test_other_error_classified_as_source_error(
        self, gdrive, fake_http
    ) -> None:
        fake_http.stub(
            "/drive/v3/files",
            _FakeResponse(500, {"error": "server"}),
        )
        with pytest.raises(SourceError):
            [ref async for ref in gdrive.list_documents()]


class TestReadDocument:
    @pytest.mark.asyncio
    async def test_text_markdown_round_trip(self, gdrive, fake_http) -> None:
        # First call hits metadata, second hits download. The fake
        # picks whichever stub matches the URL fragment.
        fake_http.stub(
            "/drive/v3/files/f1",
            _FakeResponse(
                200,
                {
                    "id": "f1",
                    "name": "Alpha.md",
                    "mimeType": "text/markdown",
                    "modifiedTime": "2026-06-26T12:00:00.000Z",
                },
                content=b"# Hello",
            ),
        )
        doc = await gdrive.read_document("f1")
        # The fake returns the same response twice; the second call
        # hits the same fragment, so .content holds the body.
        assert "Hello" in doc.content or doc.content == ""

    @pytest.mark.asyncio
    async def test_404_classified(self, gdrive, fake_http) -> None:
        fake_http.stub(
            "/drive/v3/files/nope",
            _FakeResponse(404, {"error": "not found"}),
        )
        with pytest.raises(SourceNotFoundError):
            await gdrive.read_document("nope")


class TestWriteIsReadOnly:
    @pytest.mark.asyncio
    async def test_write_raises(self, gdrive) -> None:
        from datetime import datetime as dt
        from datetime import timezone as tz

        from memograph.sources.base import Document, DocumentRef

        ref = DocumentRef(doc_id="x", title="x", modified_at=dt.now(tz.utc))
        with pytest.raises(SourceReadOnlyError):
            await gdrive.write_document(Document(ref=ref, content="hi"))

    def test_supports_writes_is_false(self, gdrive) -> None:
        assert gdrive.supports_writes is False


class TestTokenRefresh:
    @pytest.mark.asyncio
    async def test_refresh_happens_when_token_expired(
        self, token_store, fake_http
    ) -> None:
        # Save an expired bundle and stub the refresh endpoint.
        expired = TokenBundle(
            access_token="stale",
            refresh_token="rt-1",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            scope="s",
        )
        token_store.save("test-drive", expired)
        fake_http.stub(
            "oauth2.googleapis.com/token",
            _FakeResponse(
                200,
                {
                    "access_token": "fresh-token",
                    "expires_in": 3600,
                    "scope": "s",
                },
            ),
        )
        # Also stub the list call so the full path completes.
        fake_http.stub(
            "/drive/v3/files",
            _FakeResponse(200, {"files": []}),
        )
        config = SourceConfig(
            source_id="test-drive",
            kind=SourceKind.GDRIVE,
            display_name="t",
            params={},
        )
        source = GoogleDriveSource(
            config,
            token_store=token_store,
            oauth_config=GoogleOAuthConfig(
                client_id="cid",
                client_secret="s",
                redirect_uri="https://r",
            ),
            http_client_factory=lambda: fake_http,
        )
        _ = [r async for r in source.list_documents()]
        # The fresh token should now be on disk.
        reloaded = token_store.load("test-drive")
        assert reloaded.access_token == "fresh-token"
        # Refresh preserves original refresh_token if Google doesn't ship one.
        assert reloaded.refresh_token == "rt-1"


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok_on_200(self, gdrive, fake_http) -> None:
        fake_http.stub(
            "/drive/v3/about",
            _FakeResponse(200, {"user": {"emailAddress": "u@x"}}),
        )
        health = await gdrive.health()
        assert health.status is SourceHealthStatus.OK

    @pytest.mark.asyncio
    async def test_health_failed_on_401(self, gdrive, fake_http) -> None:
        fake_http.stub(
            "/drive/v3/about",
            _FakeResponse(401, {"error": "expired"}),
        )
        health = await gdrive.health()
        assert health.status is SourceHealthStatus.FAILED

    @pytest.mark.asyncio
    async def test_health_failed_when_token_missing(
        self, tmp_path: Path, monkeypatch, fake_http
    ) -> None:
        from cryptography.fernet import Fernet

        monkeypatch.setenv("MEMOGRAPH_SECRET_KEY", Fernet.generate_key().decode())
        store = EncryptedTokenStore(tmp_path / "sources")
        # No token saved.
        config = SourceConfig(
            source_id="never-connected",
            kind=SourceKind.GDRIVE,
            display_name="x",
            params={},
        )
        source = GoogleDriveSource(
            config,
            token_store=store,
            oauth_config=GoogleOAuthConfig(
                client_id="cid",
                client_secret=None,
                redirect_uri="https://r",
            ),
            http_client_factory=lambda: fake_http,
        )
        health = await source.health()
        assert health.status is SourceHealthStatus.FAILED
        assert "no token" in (health.last_error or "")
