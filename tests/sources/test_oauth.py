"""Tests for the OAuth scaffolding shared by cloud Source adapters.

Covers:

* :mod:`memograph.sources.oauth.pkce` — verifier/challenge invariants
* :mod:`memograph.sources.oauth.token_store` — encryption + key derivation
* :mod:`memograph.sources.oauth.google` — auth URL builder + code exchange
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memograph.sources.oauth.google import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GoogleOAuthConfig,
    GoogleOAuthError,
    build_authorization_url,
    exchange_code_for_tokens,
    refresh_access_token,
)
from memograph.sources.oauth.pkce import new_pkce_challenge
from memograph.sources.oauth.token_store import (
    EncryptedTokenStore,
    TokenBundle,
    TokenStoreError,
    _to_fernet_key,
)


class TestPKCE:
    def test_verifier_length_in_range(self) -> None:
        pkce = new_pkce_challenge()
        # RFC 7636 §4.1: verifier is 43-128 chars after encoding.
        assert 43 <= len(pkce.verifier) <= 128

    def test_challenge_matches_sha256_of_verifier(self) -> None:
        pkce = new_pkce_challenge()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(pkce.verifier.encode()).digest()
        ).rstrip(b"=").decode()
        assert pkce.challenge == expected
        assert pkce.method == "S256"

    def test_each_call_is_unique(self) -> None:
        a = new_pkce_challenge()
        b = new_pkce_challenge()
        assert a.verifier != b.verifier
        assert a.challenge != b.challenge


class TestFernetKeyDerivation:
    def test_passthrough_for_valid_fernet_key(self) -> None:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        assert _to_fernet_key(key) == key

    def test_derives_from_arbitrary_string(self) -> None:
        out = _to_fernet_key("any password works")
        # Result must be a 44-character urlsafe-base64 string.
        assert len(out) == 44
        # And must decrypt as a valid Fernet key.
        from cryptography.fernet import Fernet

        Fernet(out)  # raises if invalid

    def test_derivation_is_deterministic(self) -> None:
        a = _to_fernet_key("same input")
        b = _to_fernet_key("same input")
        assert a == b


class TestEncryptedTokenStore:
    @pytest.fixture
    def store(self, tmp_path: Path, monkeypatch) -> EncryptedTokenStore:
        from cryptography.fernet import Fernet

        monkeypatch.setenv("MEMOGRAPH_SECRET_KEY", Fernet.generate_key().decode())
        return EncryptedTokenStore(tmp_path / "sources")

    @pytest.fixture
    def bundle(self) -> TokenBundle:
        return TokenBundle(
            access_token="ya29.test-access",
            refresh_token="1//test-refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope="https://www.googleapis.com/auth/drive.readonly",
            token_type="Bearer",
            provider="google",
        )

    def test_round_trip(self, store: EncryptedTokenStore, bundle: TokenBundle) -> None:
        store.save("test", bundle)
        loaded = store.load("test")
        assert loaded.access_token == bundle.access_token
        assert loaded.refresh_token == bundle.refresh_token
        assert loaded.scope == bundle.scope

    def test_load_missing_raises(self, store: EncryptedTokenStore) -> None:
        with pytest.raises(TokenStoreError, match="no token saved"):
            store.load("never-existed")

    def test_delete_idempotent(
        self, store: EncryptedTokenStore, bundle: TokenBundle
    ) -> None:
        store.save("x", bundle)
        assert store.delete("x") is True
        assert store.delete("x") is False

    def test_missing_secret_key_raises(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("MEMOGRAPH_SECRET_KEY", raising=False)
        with pytest.raises(TokenStoreError, match="MEMOGRAPH_SECRET_KEY"):
            EncryptedTokenStore(tmp_path)

    def test_key_rotation_yields_clear_error(
        self,
        tmp_path: Path,
        monkeypatch,
        bundle: TokenBundle,
    ) -> None:
        from cryptography.fernet import Fernet

        key1 = Fernet.generate_key().decode()
        monkeypatch.setenv("MEMOGRAPH_SECRET_KEY", key1)
        store_a = EncryptedTokenStore(tmp_path)
        store_a.save("x", bundle)

        # Rotate the key without re-encrypting.
        monkeypatch.setenv("MEMOGRAPH_SECRET_KEY", Fernet.generate_key().decode())
        store_b = EncryptedTokenStore(tmp_path)
        with pytest.raises(TokenStoreError, match="decryption failed"):
            store_b.load("x")

    def test_bundle_is_expired_detection(self) -> None:
        past = TokenBundle(
            access_token="x",
            refresh_token="y",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            scope="s",
        )
        future = TokenBundle(
            access_token="x",
            refresh_token="y",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope="s",
        )
        no_expiry = TokenBundle(
            access_token="x", refresh_token="y", expires_at=None, scope="s"
        )
        assert past.is_expired() is True
        assert future.is_expired() is False
        # A token without an expiry is treated as fresh — Google
        # always sends one, but our adapter must not blow up if it
        # doesn't.
        assert no_expiry.is_expired() is False


class TestAuthorizationUrl:
    def test_includes_all_required_params(self) -> None:
        config = GoogleOAuthConfig(
            client_id="cid",
            client_secret=None,
            redirect_uri="https://example/callback",
        )
        url = build_authorization_url(
            config, state="opaque-state", code_challenge="abc"
        )
        assert url.startswith(GOOGLE_AUTHORIZATION_ENDPOINT)
        for piece in (
            "client_id=cid",
            "redirect_uri=https",
            "response_type=code",
            "state=opaque-state",
            "code_challenge=abc",
            "code_challenge_method=S256",
            "access_type=offline",
            "prompt=consent",
        ):
            assert piece in url, piece

    def test_scope_is_url_encoded(self) -> None:
        config = GoogleOAuthConfig(
            client_id="cid",
            client_secret=None,
            redirect_uri="https://example/callback",
            scopes=("https://www.googleapis.com/auth/drive.readonly",),
        )
        url = build_authorization_url(
            config, state="s", code_challenge="c"
        )
        # urlencode escapes ":" and "/" so the scheme appears as "https%3A%2F%2F".
        assert "scope=" in url
        assert "%3A%2F%2F" in url


class TestGoogleOAuthConfigFromEnv:
    def test_missing_client_id_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("MEMOGRAPH_GOOGLE_CLIENT_ID", raising=False)
        with pytest.raises(GoogleOAuthError, match="CLIENT_ID"):
            GoogleOAuthConfig.from_env(default_redirect="https://x")

    def test_uses_env_redirect_when_set(self, monkeypatch) -> None:
        monkeypatch.setenv("MEMOGRAPH_GOOGLE_CLIENT_ID", "cid")
        monkeypatch.setenv(
            "MEMOGRAPH_GOOGLE_REDIRECT_URI", "https://example/cb"
        )
        config = GoogleOAuthConfig.from_env()
        assert config.redirect_uri == "https://example/cb"

    def test_default_redirect_used_when_env_absent(self, monkeypatch) -> None:
        monkeypatch.setenv("MEMOGRAPH_GOOGLE_CLIENT_ID", "cid")
        monkeypatch.delenv("MEMOGRAPH_GOOGLE_REDIRECT_URI", raising=False)
        config = GoogleOAuthConfig.from_env(default_redirect="https://fallback/cb")
        assert config.redirect_uri == "https://fallback/cb"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeHTTP:
    """Minimal HTTP-client stub matching the OAuth module's Protocol."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.response: _FakeResponse = _FakeResponse(200, {})

    async def post(self, url: str, data: dict) -> _FakeResponse:
        self.requests.append((url, data))
        return self.response


class TestExchangeCodeForTokens:
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        http = _FakeHTTP()
        http.response = _FakeResponse(
            200,
            {
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "scope": "s",
                "token_type": "Bearer",
            },
        )
        config = GoogleOAuthConfig(
            client_id="cid",
            client_secret="secret",
            redirect_uri="https://r",
        )
        bundle = await exchange_code_for_tokens(
            http, config, code="abc", code_verifier="ver"
        )
        assert bundle.access_token == "at"
        assert bundle.refresh_token == "rt"
        assert bundle.scope == "s"
        # Verifier was sent in the body.
        url, body = http.requests[-1]
        assert body["code_verifier"] == "ver"
        assert body["client_secret"] == "secret"

    @pytest.mark.asyncio
    async def test_non_200_raises(self) -> None:
        http = _FakeHTTP()
        http.response = _FakeResponse(400, {}, text="invalid_grant")
        config = GoogleOAuthConfig(
            client_id="cid", client_secret=None, redirect_uri="https://r"
        )
        with pytest.raises(GoogleOAuthError, match="invalid_grant"):
            await exchange_code_for_tokens(
                http, config, code="bad", code_verifier="v"
            )

    @pytest.mark.asyncio
    async def test_missing_access_token_raises(self) -> None:
        http = _FakeHTTP()
        http.response = _FakeResponse(200, {"refresh_token": "rt"})
        config = GoogleOAuthConfig(
            client_id="cid", client_secret=None, redirect_uri="https://r"
        )
        with pytest.raises(GoogleOAuthError, match="missing access_token"):
            await exchange_code_for_tokens(
                http, config, code="bad", code_verifier="v"
            )


class TestRefreshAccessToken:
    @pytest.mark.asyncio
    async def test_preserves_original_refresh_when_response_omits(self) -> None:
        http = _FakeHTTP()
        http.response = _FakeResponse(
            200,
            {
                "access_token": "new-at",
                "expires_in": 3600,
                "scope": "s",
            },
        )
        config = GoogleOAuthConfig(
            client_id="cid", client_secret=None, redirect_uri="https://r"
        )
        bundle = await refresh_access_token(
            http, config, refresh_token="original-rt"
        )
        assert bundle.refresh_token == "original-rt"
        assert bundle.access_token == "new-at"
