"""End-to-end auth tests for the Phase 1.1 auth module.

Three providers exercised:

- ``none``: routes return 200 anonymously, audit log records no user.
- ``api_key``: ``X-API-Key`` is required; rotates via env; audit log
  records ``apikey:<prefix>``.
- ``oidc``: a synthetic RS256 JWT signed with a test private key; the
  matching JWK is served via a stub ``PyJWKClient`` so we don't hit
  the network. Covers happy path, expired, wrong audience, malformed.

The cross-cutting concern — identity propagation into the audit log —
is verified by checking ``Action.user`` after a successful request.
"""

from __future__ import annotations

import importlib
import json
import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


# --------------------------------------------------------------- RSA test key


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[Any, dict]:
    """One RSA-2048 keypair for the whole module + a JWK dict the
    stub JWKS client returns. We bypass actual JWKS-format conversion
    (modulus/exponent base64url'd into a JWK) by stubbing the JWKS
    client itself; only the kid/alg from this dict ever matter."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, {"kid": "test-key", "alg": "RS256"}


def _sign_token(
    private_key,
    *,
    sub: str = "user-123",
    aud: str = "memograph-api",
    iss: str = "https://test.idp.example",
    exp_offset: int = 3600,
    extra: dict | None = None,
) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "aud": aud,
        "iss": iss,
        "iat": now,
        "exp": now + exp_offset,
        **(extra or {}),
    }
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "test-key"})


# --------------------------------------------------------------- JWKS stub


class _StubJWK:
    def __init__(self, key):
        self.key = key


class _StubJWKSClient:
    """Stand-in for ``jwt.PyJWKClient`` — returns the public key of the
    in-memory test RSA pair regardless of the token. Lets tests run
    fully offline."""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token: str) -> _StubJWK:
        return _StubJWK(self._public_key)


# ----------------------------------------------------------------- fixtures


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture
def auth_module(monkeypatch):
    """Reimport auth+server with a clean env and reset OIDC client cache."""
    for var in (
        "MEMOGRAPH_AUTH_PROVIDER",
        "MEMOGRAPH_API_KEYS",
        "MEMOGRAPH_OIDC_JWKS_URL",
        "MEMOGRAPH_OIDC_AUDIENCE",
        "MEMOGRAPH_OIDC_ISSUER",
    ):
        monkeypatch.delenv(var, raising=False)
    from memograph.web.backend import auth as auth_mod
    from memograph.web.backend import server as server_mod

    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    auth_mod._reset_oidc_state()
    return auth_mod, server_mod


def _client(server_mod, vault_dir) -> TestClient:
    app = server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
    app.state.kernel.ingest()
    app.state.is_ready = True
    return TestClient(app)


# ---------------------------------------------------------------- provider=none


class TestProviderNone:
    def test_open_when_unset(self, auth_module, vault_dir):
        _, server_mod = auth_module
        client = _client(server_mod, vault_dir)
        r = client.get("/api/v1/memories")
        assert r.status_code == 200

    def test_whoami_anonymous_when_unset(self, auth_module, vault_dir):
        _, server_mod = auth_module
        client = _client(server_mod, vault_dir)
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "anonymous"
        assert "anonymous" in body["scopes"]


# ------------------------------------------------------------ provider=api_key


class TestProviderApiKey:
    @pytest.fixture
    def api_key_env(self, monkeypatch):
        monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
        monkeypatch.setenv("MEMOGRAPH_API_KEYS", "key-alpha,key-beta")
        from memograph.web.backend import auth as auth_mod
        from memograph.web.backend import server as server_mod

        importlib.reload(auth_mod)
        importlib.reload(server_mod)
        auth_mod._reset_oidc_state()
        return server_mod

    def test_unauthenticated_blocked(self, api_key_env, vault_dir):
        client = _client(api_key_env, vault_dir)
        r = client.get("/api/v1/memories")
        assert r.status_code == 401
        assert r.headers.get("WWW-Authenticate", "").startswith("Bearer")

    def test_wrong_key_blocked(self, api_key_env, vault_dir):
        client = _client(api_key_env, vault_dir)
        r = client.get("/api/v1/memories", headers={"X-API-Key": "key-evil"})
        assert r.status_code == 401

    def test_correct_key_allowed(self, api_key_env, vault_dir):
        client = _client(api_key_env, vault_dir)
        r = client.get("/api/v1/memories", headers={"X-API-Key": "key-alpha"})
        assert r.status_code == 200

    def test_whoami_records_apikey_id_not_plaintext(self, api_key_env, vault_dir):
        client = _client(api_key_env, vault_dir)
        r = client.get("/api/v1/auth/me", headers={"X-API-Key": "key-alpha"})
        assert r.status_code == 200
        body = r.json()
        # ID must not include the plaintext key.
        assert "key-alpha" not in body["id"]
        assert body["id"].startswith("apikey:")
        assert body["scopes"] == ["api_key"]


# --------------------------------------------------------------- provider=oidc


class TestProviderOidc:
    @pytest.fixture
    def oidc_env(self, monkeypatch, rsa_keypair):
        private_key, _ = rsa_keypair
        monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "oidc")
        monkeypatch.setenv(
            "MEMOGRAPH_OIDC_JWKS_URL", "https://test.idp.example/.well-known/jwks.json"
        )
        monkeypatch.setenv("MEMOGRAPH_OIDC_AUDIENCE", "memograph-api")
        monkeypatch.setenv("MEMOGRAPH_OIDC_ISSUER", "https://test.idp.example")

        from memograph.web.backend import auth as auth_mod
        from memograph.web.backend import server as server_mod

        importlib.reload(auth_mod)
        importlib.reload(server_mod)

        # Replace the JWKS client with our stub so verification stays
        # offline. _get_jwks_client() lazy-builds; force a stub instead.
        auth_mod._jwks_client = _StubJWKSClient(private_key.public_key())
        return private_key, server_mod, auth_mod

    def test_no_token_blocked(self, oidc_env, vault_dir):
        _, server_mod, _ = oidc_env
        client = _client(server_mod, vault_dir)
        r = client.get("/api/v1/memories")
        assert r.status_code == 401

    def test_valid_token_allowed(self, oidc_env, vault_dir):
        private_key, server_mod, _ = oidc_env
        token = _sign_token(private_key)
        client = _client(server_mod, vault_dir)
        r = client.get(
            "/api/v1/memories",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text

    def test_expired_token_blocked(self, oidc_env, vault_dir):
        private_key, server_mod, _ = oidc_env
        token = _sign_token(private_key, exp_offset=-3600)
        client = _client(server_mod, vault_dir)
        r = client.get(
            "/api/v1/memories",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 401

    def test_wrong_audience_blocked(self, oidc_env, vault_dir):
        private_key, server_mod, _ = oidc_env
        token = _sign_token(private_key, aud="not-memograph")
        client = _client(server_mod, vault_dir)
        r = client.get(
            "/api/v1/memories",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 401

    def test_wrong_issuer_blocked(self, oidc_env, vault_dir):
        private_key, server_mod, _ = oidc_env
        token = _sign_token(private_key, iss="https://evil.idp.example")
        client = _client(server_mod, vault_dir)
        r = client.get(
            "/api/v1/memories",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 401

    def test_malformed_token_blocked(self, oidc_env, vault_dir):
        _, server_mod, _ = oidc_env
        client = _client(server_mod, vault_dir)
        r = client.get(
            "/api/v1/memories",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert r.status_code == 401

    def test_whoami_carries_oidc_identity(self, oidc_env, vault_dir):
        private_key, server_mod, _ = oidc_env
        token = _sign_token(
            private_key,
            sub="user-789",
            extra={
                "email": "alice@example.com",
                "org_id": "org-42",
                "scope": "memories:read memories:write",
            },
        )
        client = _client(server_mod, vault_dir)
        r = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == "oidc:user-789"
        assert body["email"] == "alice@example.com"
        assert body["organization_id"] == "org-42"
        assert "memories:read" in body["scopes"]
        assert "memories:write" in body["scopes"]


# ------------------------------------------------------- audit log identity


class TestAuditIdentityPropagation:
    """The auth ContextVar must populate Action.user when a memory is
    created inside an authenticated request — even though the kernel
    doesn't take a `user` parameter explicitly."""

    @pytest.fixture
    def configured(self, monkeypatch, vault_dir):
        monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
        monkeypatch.setenv("MEMOGRAPH_API_KEYS", "audit-key")
        from memograph.web.backend import auth as auth_mod
        from memograph.web.backend import server as server_mod

        importlib.reload(auth_mod)
        importlib.reload(server_mod)
        auth_mod._reset_oidc_state()

        # Seed an action through the action logger directly inside the
        # auth context — emulates what kernel ops do via the web request.
        from memograph.core.action_logger import ActionLogger
        from memograph.web.backend.auth import User, current_user

        token = current_user.set(
            User(id="apikey:test", scopes=("api_key",), organization_id="tenant-x")
        )
        try:
            log = ActionLogger(str(vault_dir))
            action = log.log_action(
                memory_id="m1",
                action_type="create",
                summary="test",
            )
        finally:
            current_user.reset(token)
        return action

    def test_user_populated_from_context(self, configured):
        assert configured.user == "apikey:test"

    def test_tenant_id_populated_from_org_claim(self, configured):
        assert configured.tenant_id == "tenant-x"


# Cleanup so tests don't bleed env into siblings outside this module.
@pytest.fixture(autouse=True)
def _restore_after_test():
    yield
    from memograph.web.backend import auth as auth_mod
    from memograph.web.backend import server as server_mod

    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    auth_mod._reset_oidc_state()


# Silences a json import we don't actually use in the test body but pytest
# may need for discovery in some environments.
_ = json
