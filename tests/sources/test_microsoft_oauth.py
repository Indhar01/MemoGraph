"""Tests for :mod:`memograph.sources.oauth.microsoft`.

Mirror of :mod:`tests.sources.test_oauth` for the Google flow. The
Microsoft module shares the same shape, but the authorization URL
is tenant-scoped and the token endpoint expects ``scope`` on
refresh too — these are the bits we pin down here.
"""

from __future__ import annotations

import pytest

from memograph.sources.oauth.microsoft import (
    MICROSOFT_DEFAULT_TENANT,
    MicrosoftOAuthConfig,
    MicrosoftOAuthError,
    build_authorization_url,
    exchange_code_for_tokens,
    refresh_access_token,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeHTTP:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.response: _FakeResponse = _FakeResponse(200, {})

    async def post(self, url: str, data: dict) -> _FakeResponse:
        self.requests.append((url, data))
        return self.response


class TestAuthorizationUrl:
    def test_uses_common_tenant_by_default(self) -> None:
        config = MicrosoftOAuthConfig(
            client_id="cid",
            client_secret=None,
            redirect_uri="https://example/callback",
        )
        url = build_authorization_url(
            config, state="opaque", code_challenge="c"
        )
        assert "login.microsoftonline.com/common/" in url
        for piece in (
            "client_id=cid",
            "response_type=code",
            "response_mode=query",
            "state=opaque",
            "code_challenge=c",
            "code_challenge_method=S256",
            "prompt=select_account",
        ):
            assert piece in url, piece

    def test_honours_custom_tenant(self) -> None:
        config = MicrosoftOAuthConfig(
            client_id="cid",
            client_secret=None,
            redirect_uri="https://example/callback",
            tenant="contoso.onmicrosoft.com",
        )
        url = build_authorization_url(
            config, state="s", code_challenge="c"
        )
        assert "/contoso.onmicrosoft.com/oauth2/v2.0/authorize" in url

    def test_scope_is_url_encoded(self) -> None:
        config = MicrosoftOAuthConfig(
            client_id="cid",
            client_secret=None,
            redirect_uri="https://example/callback",
            scopes=("Files.Read", "offline_access"),
        )
        url = build_authorization_url(
            config, state="s", code_challenge="c"
        )
        # urlencode joins with + between the two scopes (form-encoded).
        # Both + and %20 are valid here per RFC 3986; the AS accepts either.
        assert "scope=Files.Read+offline_access" in url


class TestFromEnv:
    def test_missing_client_id_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("MEMOGRAPH_MICROSOFT_CLIENT_ID", raising=False)
        with pytest.raises(MicrosoftOAuthError, match="CLIENT_ID"):
            MicrosoftOAuthConfig.from_env(default_redirect="https://x")

    def test_defaults_to_common_tenant(self, monkeypatch) -> None:
        monkeypatch.setenv("MEMOGRAPH_MICROSOFT_CLIENT_ID", "cid")
        monkeypatch.delenv("MEMOGRAPH_MICROSOFT_TENANT", raising=False)
        config = MicrosoftOAuthConfig.from_env(default_redirect="https://r")
        assert config.tenant == MICROSOFT_DEFAULT_TENANT

    def test_uses_env_tenant_when_set(self, monkeypatch) -> None:
        monkeypatch.setenv("MEMOGRAPH_MICROSOFT_CLIENT_ID", "cid")
        monkeypatch.setenv("MEMOGRAPH_MICROSOFT_TENANT", "organizations")
        config = MicrosoftOAuthConfig.from_env(default_redirect="https://r")
        assert config.tenant == "organizations"


class TestExchangeCode:
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        http = _FakeHTTP()
        http.response = _FakeResponse(
            200,
            {
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "scope": "Files.Read offline_access",
                "token_type": "Bearer",
            },
        )
        config = MicrosoftOAuthConfig(
            client_id="cid",
            client_secret="secret",
            redirect_uri="https://r",
        )
        bundle = await exchange_code_for_tokens(
            http, config, code="abc", code_verifier="ver"
        )
        assert bundle.access_token == "at"
        assert bundle.refresh_token == "rt"
        assert bundle.provider == "microsoft"
        # Verifier and scope are in the body.
        _, body = http.requests[-1]
        assert body["code_verifier"] == "ver"
        assert body["scope"] == "Files.Read offline_access"
        assert body["client_secret"] == "secret"

    @pytest.mark.asyncio
    async def test_non_200_raises(self) -> None:
        http = _FakeHTTP()
        http.response = _FakeResponse(400, {}, text="AADSTS70008")
        config = MicrosoftOAuthConfig(
            client_id="cid", client_secret=None, redirect_uri="https://r"
        )
        with pytest.raises(MicrosoftOAuthError, match="AADSTS70008"):
            await exchange_code_for_tokens(
                http, config, code="bad", code_verifier="v"
            )


class TestRefresh:
    @pytest.mark.asyncio
    async def test_preserves_original_refresh_when_response_omits(self) -> None:
        http = _FakeHTTP()
        http.response = _FakeResponse(
            200,
            {"access_token": "new-at", "expires_in": 3600, "scope": "s"},
        )
        config = MicrosoftOAuthConfig(
            client_id="cid", client_secret=None, redirect_uri="https://r"
        )
        bundle = await refresh_access_token(
            http, config, refresh_token="original-rt"
        )
        assert bundle.access_token == "new-at"
        assert bundle.refresh_token == "original-rt"

    @pytest.mark.asyncio
    async def test_adopts_new_refresh_when_provided(self) -> None:
        http = _FakeHTTP()
        http.response = _FakeResponse(
            200,
            {
                "access_token": "new-at",
                "refresh_token": "rolled-rt",
                "expires_in": 3600,
                "scope": "s",
            },
        )
        config = MicrosoftOAuthConfig(
            client_id="cid", client_secret=None, redirect_uri="https://r"
        )
        bundle = await refresh_access_token(
            http, config, refresh_token="original-rt"
        )
        # Rolling refresh tokens — Microsoft typically ships one.
        assert bundle.refresh_token == "rolled-rt"
