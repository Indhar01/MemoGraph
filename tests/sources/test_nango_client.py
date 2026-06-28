"""Tests for :class:`memograph.sources.nango_client.NangoClient`.

The client is a thin HTTP wrapper. We stub ``httpx.AsyncClient`` via
the same ``_FakeHttpx`` pattern used elsewhere in the suite so no
real Nango instance is needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from memograph.sources.base import (
    SourceAuthError,
    SourceError,
    SourceKind,
    SourceNotFoundError,
)
from memograph.sources.nango_client import (
    NangoClient,
    NangoConfig,
    NangoConfigError,
)


# --- fake httpx -----------------------------------------------------------


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
    """Records every call; returns stubbed responses keyed by URL fragment."""

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

    async def get(
        self, url: str, params: dict | None = None, headers: dict | None = None
    ) -> _FakeResponse:
        self.calls.append(
            {"method": "GET", "url": url, "params": params, "headers": headers}
        )
        return self._lookup("GET", url)

    async def post(
        self,
        url: str,
        json: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> _FakeResponse:
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

    async def delete(self, url: str, params: dict | None = None) -> _FakeResponse:
        self.calls.append({"method": "DELETE", "url": url, "params": params})
        return self._lookup("DELETE", url)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_http() -> _FakeHttpx:
    return _FakeHttpx()


@pytest.fixture
def client(fake_http) -> NangoClient:
    cfg = NangoConfig(
        base_url="http://nango:3003",
        secret_key="sk-test",
        webhook_secret="whsec-test",
    )
    return NangoClient(cfg, http_client=fake_http)


# --- config ---------------------------------------------------------------


class TestNangoConfig:
    def test_from_env_requires_base_url(self, monkeypatch) -> None:
        monkeypatch.delenv("MEMOGRAPH_NANGO_BASE_URL", raising=False)
        with pytest.raises(NangoConfigError, match="BASE_URL"):
            NangoConfig.from_env()

    def test_from_env_requires_secret_key(self, monkeypatch) -> None:
        monkeypatch.setenv("MEMOGRAPH_NANGO_BASE_URL", "http://x")
        monkeypatch.delenv("MEMOGRAPH_NANGO_SECRET_KEY", raising=False)
        with pytest.raises(NangoConfigError, match="SECRET_KEY"):
            NangoConfig.from_env()

    def test_from_env_strips_trailing_slash(self, monkeypatch) -> None:
        monkeypatch.setenv("MEMOGRAPH_NANGO_BASE_URL", "http://x/")
        monkeypatch.setenv("MEMOGRAPH_NANGO_SECRET_KEY", "sk")
        cfg = NangoConfig.from_env()
        assert cfg.base_url == "http://x"


# --- connect sessions -----------------------------------------------------


class TestConnectSession:
    @pytest.mark.asyncio
    async def test_happy_path(self, client, fake_http) -> None:
        future = datetime.now(timezone.utc) + timedelta(minutes=30)
        fake_http.stub(
            "POST",
            "/connect/sessions",
            _FakeResponse(
                201,
                {
                    "data": {
                        "token": "tok-abc",
                        "expires_at": future.isoformat(),
                        "connect_link": "https://connect.example/abc",
                    }
                },
            ),
        )
        session = await client.create_connect_session(
            kind=SourceKind.GDRIVE,
            tenant_id="tenant-1",
            source_id="my-drive",
            end_user_id="user-42",
            end_user_email="x@y.test",
            display_name="My Drive",
        )
        assert session.token == "tok-abc"
        assert session.connect_link.startswith("https://connect.")

        # Tags carry our routing data forward.
        body = fake_http.calls[-1]["json"]
        assert body["allowed_integrations"] == ["google-drive"]
        tags = body["tags"]
        assert tags["end_user_id"] == "user-42"
        assert tags["end_user_email"] == "x@y.test"
        assert tags["memograph_tenant_id"] == "tenant-1"
        assert tags["memograph_source_id"] == "my-drive"
        assert tags["memograph_kind"] == "gdrive"
        assert tags["memograph_display_name"] == "My Drive"

    @pytest.mark.asyncio
    async def test_rejects_non_oauth_kind(self, client) -> None:
        with pytest.raises(SourceError, match="only the OAuth cloud kinds"):
            await client.create_connect_session(
                kind=SourceKind.LOCAL,
                tenant_id=None,
                source_id="x",
                end_user_id="u",
            )

    @pytest.mark.asyncio
    async def test_401_is_config_error(self, client, fake_http) -> None:
        fake_http.stub(
            "POST",
            "/connect/sessions",
            _FakeResponse(401, {"error": "bad key"}),
        )
        with pytest.raises(NangoConfigError, match="secret key"):
            await client.create_connect_session(
                kind=SourceKind.GDRIVE,
                tenant_id=None,
                source_id="x",
                end_user_id="u",
            )

    @pytest.mark.asyncio
    async def test_500_is_source_error(self, client, fake_http) -> None:
        fake_http.stub(
            "POST",
            "/connect/sessions",
            _FakeResponse(500, {"error": "server down"}),
        )
        with pytest.raises(SourceError):
            await client.create_connect_session(
                kind=SourceKind.GDRIVE,
                tenant_id=None,
                source_id="x",
                end_user_id="u",
            )


# --- get_connection -------------------------------------------------------


class TestGetConnection:
    @pytest.mark.asyncio
    async def test_healthy(self, client, fake_http) -> None:
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
                    "metadata": {"email": "x@y.test"},
                    "created_at": "2026-06-26T10:00:00Z",
                    "updated_at": "2026-06-26T10:00:00Z",
                },
            ),
        )
        info = await client.get_connection(
            connection_id="conn-1", kind=SourceKind.GDRIVE
        )
        assert info.connection_id == "conn-1"
        assert info.has_auth_error is False
        assert info.metadata["email"] == "x@y.test"

    @pytest.mark.asyncio
    async def test_424_is_auth_error(self, client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/connections/conn-1",
            _FakeResponse(424, {"error": "refresh exhausted"}),
        )
        with pytest.raises(SourceAuthError, match="refreshed"):
            await client.get_connection(connection_id="conn-1", kind=SourceKind.GDRIVE)

    @pytest.mark.asyncio
    async def test_auth_error_in_payload(self, client, fake_http) -> None:
        # Nango can return 200 with an in-band auth-error marker.
        fake_http.stub(
            "GET",
            "/connections/conn-1",
            _FakeResponse(
                200,
                {
                    "connection_id": "conn-1",
                    "provider_config_key": "google-drive",
                    "provider": "google-drive",
                    "errors": [{"type": "auth", "log_id": "lg-1"}],
                    "metadata": {},
                    "created_at": None,
                    "updated_at": None,
                },
            ),
        )
        with pytest.raises(SourceAuthError):
            await client.get_connection(connection_id="conn-1", kind=SourceKind.GDRIVE)

    @pytest.mark.asyncio
    async def test_404_is_not_found(self, client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/connections/missing",
            _FakeResponse(404, {"error": "not found"}),
        )
        with pytest.raises(SourceNotFoundError):
            await client.get_connection(connection_id="missing", kind=SourceKind.GDRIVE)


# --- proxy ----------------------------------------------------------------


class TestProxy:
    @pytest.mark.asyncio
    async def test_proxy_get_forwards_headers(self, client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/proxy/drive/v3/files",
            _FakeResponse(200, {"files": []}),
        )
        resp = await client.proxy_get(
            connection_id="conn-1",
            kind=SourceKind.GDRIVE,
            path="drive/v3/files",
            params={"pageSize": "50"},
        )
        assert resp.status_code == 200
        call = fake_http.calls[-1]
        assert call["headers"]["Provider-Config-Key"] == "google-drive"
        assert call["headers"]["Connection-Id"] == "conn-1"
        assert call["params"] == {"pageSize": "50"}

    @pytest.mark.asyncio
    async def test_proxy_get_bytes_404_raises_not_found(
        self, client, fake_http
    ) -> None:
        fake_http.stub(
            "GET",
            "/proxy/drive/v3/files/missing",
            _FakeResponse(404, {"error": "gone"}, text="gone"),
        )
        with pytest.raises(SourceNotFoundError):
            await client.proxy_get_bytes(
                connection_id="conn-1",
                kind=SourceKind.GDRIVE,
                path="drive/v3/files/missing",
            )

    @pytest.mark.asyncio
    async def test_proxy_get_bytes_401_raises_auth(self, client, fake_http) -> None:
        fake_http.stub(
            "GET",
            "/proxy/drive/v3/files/x",
            _FakeResponse(401, {"error": "expired"}, text="expired"),
        )
        with pytest.raises(SourceAuthError):
            await client.proxy_get_bytes(
                connection_id="conn-1",
                kind=SourceKind.GDRIVE,
                path="drive/v3/files/x",
            )


# --- delete connection ----------------------------------------------------


class TestDelete:
    @pytest.mark.asyncio
    async def test_returns_true_on_204(self, client, fake_http) -> None:
        fake_http.stub("DELETE", "/connections/conn-1", _FakeResponse(204, None))
        removed = await client.delete_connection(
            connection_id="conn-1", kind=SourceKind.GDRIVE
        )
        assert removed is True

    @pytest.mark.asyncio
    async def test_returns_false_on_404(self, client, fake_http) -> None:
        fake_http.stub("DELETE", "/connections/conn-x", _FakeResponse(404, None))
        removed = await client.delete_connection(
            connection_id="conn-x", kind=SourceKind.GDRIVE
        )
        assert removed is False


# --- webhook signature ----------------------------------------------------


class TestWebhookSignature:
    def test_valid_signature_accepted(self, client) -> None:
        import hashlib
        import hmac

        body = b'{"type":"auth","operation":"creation"}'
        expected = hmac.new(b"whsec-test", body, hashlib.sha256).hexdigest()
        assert client.verify_webhook_signature(raw_body=body, signature=expected)
        # Tolerates "sha256=..." prefix.
        assert client.verify_webhook_signature(
            raw_body=body, signature=f"sha256={expected}"
        )

    def test_bad_signature_rejected(self, client) -> None:
        body = b'{"type":"auth"}'
        assert not client.verify_webhook_signature(raw_body=body, signature="0" * 64)

    def test_missing_signature_rejected_when_secret_set(self, client) -> None:
        body = b'{"type":"auth"}'
        assert not client.verify_webhook_signature(raw_body=body, signature=None)

    def test_missing_secret_logs_and_accepts(self) -> None:
        # When the operator hasn't set the webhook secret (dev mode),
        # the client returns True with a warning. Production setups
        # must set the secret.
        unsigned = NangoClient(
            NangoConfig(
                base_url="http://x",
                secret_key="sk",
                webhook_secret=None,
            ),
            http_client=_FakeHttpx(),
        )
        assert unsigned.verify_webhook_signature(raw_body=b"x", signature=None)
