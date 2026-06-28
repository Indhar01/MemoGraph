"""Tests for the Nango integration routes.

Covers:

* ``POST /sources/connect-session`` — admin-scoped, returns a Nango
  session token, auto-generates source_id when omitted.
* ``POST /sources/webhook`` — public, HMAC-verified, registers a
  source on connection-creation success, skips non-auth events.
* ``GET /sources/nango/health`` — surfaces whether Nango is wired up.

The Nango client is stubbed via a tiny in-process double swapped onto
``app.state.nango_client`` so no real Nango (or even httpx) is needed.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


ADMIN_HEADER = {"X-API-Key": "admin-key"}
USER_HEADER = {"X-API-Key": "user-key"}


# --- fake NangoClient -----------------------------------------------------


class _StubNangoConfig:
    base_url = "http://nango-stub"
    public_url = "http://nango-stub"


class _StubNangoClient:
    """Mimics the public surface ``routes/nango.py`` calls."""

    def __init__(self, *, webhook_secret: bytes = b"whsec") -> None:
        self.config = _StubNangoConfig()
        self._webhook_secret = webhook_secret
        self.sessions: list[dict[str, Any]] = []

    async def create_connect_session(
        self,
        *,
        kind,
        tenant_id,
        source_id,
        end_user_id,
        end_user_email=None,
        display_name=None,
    ):
        self.sessions.append(
            {
                "kind": kind,
                "tenant_id": tenant_id,
                "source_id": source_id,
                "end_user_id": end_user_id,
                "end_user_email": end_user_email,
                "display_name": display_name,
            }
        )

        class _Session:
            token = "tok-test"
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            connect_link = None

        return _Session()

    async def list_integrations(self) -> list[dict[str, Any]]:
        # Default stub: GDrive integration is configured so health
        # checks return a populated available_integrations list.
        return [
            {"unique_key": "google-drive", "provider": "google-drive"},
        ]

    def verify_webhook_signature(
        self, *, raw_body: bytes, signature: str | None
    ) -> bool:
        if not signature:
            return False
        expected = hmac.new(self._webhook_secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.split("=", 1)[-1].strip())


def _sign(body: bytes, secret: bytes = b"whsec") -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


# --- fixtures (mirror tests/web/test_sources_routes.py) -------------------


@pytest.fixture
def sources_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "sources-root"
    root.mkdir()
    monkeypatch.setenv("MEMOGRAPH_SOURCES_ROOT", str(root))
    return root


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture
def sources_server(monkeypatch: pytest.MonkeyPatch, sources_root: Path):
    monkeypatch.delenv("MEMOGRAPH_DEBUG", raising=False)
    monkeypatch.delenv("MEMOGRAPH_LOG_JSON", raising=False)
    monkeypatch.delenv("MEMOGRAPH_TENANCY_ENABLED", raising=False)
    monkeypatch.delenv("MEMOGRAPH_READONLY", raising=False)
    monkeypatch.setenv("MEMOGRAPH_SOURCES_ENABLED", "1")
    monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
    monkeypatch.setenv("MEMOGRAPH_API_KEYS", "admin-key,user-key")

    from memograph.web.backend import auth as auth_mod
    from memograph.web.backend import server as server_mod

    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    auth_mod._reset_oidc_state()

    original = auth_mod._verify_api_key

    def _verify_with_scopes(key: str):
        user = original(key)
        if user is None:
            return None
        if key == "admin-key":
            return auth_mod.User(
                id=user.id,
                email=user.email,
                organization_id=user.organization_id,
                scopes=("api_key", "admin"),
                raw_claims=user.raw_claims,
            )
        return user

    monkeypatch.setattr(auth_mod, "_verify_api_key", _verify_with_scopes)
    return server_mod


def _client(server_module, vault_dir: Path, *, with_nango: bool = True) -> TestClient:
    app = server_module.create_app(vault_path=str(vault_dir), use_gam=False)
    app.state.kernel.ingest()
    app.state.is_ready = True
    if with_nango:
        app.state.nango_client = _StubNangoClient()
        # Re-inject into the registry so the cloud-kind dispatch works.
        app.state.source_registry._nango_client = app.state.nango_client
    return TestClient(app)


# --- connect-session ------------------------------------------------------


class TestConnectSession:
    def test_auto_generates_source_id(self, sources_server, vault_dir) -> None:
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources/connect-session",
            json={"kind": "gdrive"},
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["session_token"] == "tok-test"
        assert body["source_id"].startswith("gdrive-")

    def test_requires_admin(self, sources_server, vault_dir) -> None:
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources/connect-session",
            json={"kind": "gdrive"},
            headers=USER_HEADER,
        )
        assert r.status_code == 403

    def test_rejects_non_oauth_kind(self, sources_server, vault_dir) -> None:
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources/connect-session",
            json={"kind": "local"},
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 400
        assert "not routed through Nango" in r.json()["error"]

    def test_returns_503_when_nango_missing(self, sources_server, vault_dir) -> None:
        client = _client(sources_server, vault_dir, with_nango=False)
        r = client.post(
            "/api/v1/sources/connect-session",
            json={"kind": "gdrive"},
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 503


# --- webhook --------------------------------------------------------------


class TestWebhook:
    def test_creation_registers_source(
        self, sources_server, vault_dir, sources_root
    ) -> None:
        client = _client(sources_server, vault_dir)
        payload = {
            "type": "auth",
            "operation": "creation",
            "success": True,
            "connectionId": "conn-xyz",
            "providerConfigKey": "google-drive",
            "tags": {
                "end_user_id": "user-1",
                "memograph_source_id": "my-drive",
                "memograph_kind": "gdrive",
                "memograph_display_name": "My Drive",
            },
        }
        raw = json.dumps(payload).encode("utf-8")
        r = client.post(
            "/api/v1/sources/webhook",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Nango-Signature": _sign(raw),
            },
        )
        assert r.status_code == 204, r.text
        # Source landed on disk.
        cfg_path = sources_root / ".sources" / "my-drive.json"
        assert cfg_path.exists()
        cfg = json.loads(cfg_path.read_text())
        assert cfg["kind"] == "gdrive"
        assert cfg["params"]["nango_connection_id"] == "conn-xyz"
        # Audit logged.
        audit = (sources_root / ".sources" / "_audit.log").read_text()
        assert "source.oauth_exchange" in audit

    def test_bad_signature_rejected(self, sources_server, vault_dir) -> None:
        client = _client(sources_server, vault_dir)
        raw = b'{"type":"auth","operation":"creation","success":true}'
        r = client.post(
            "/api/v1/sources/webhook",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Nango-Signature": "0" * 64,
            },
        )
        assert r.status_code == 401

    def test_failure_event_is_acknowledged_but_not_registered(
        self, sources_server, vault_dir, sources_root
    ) -> None:
        client = _client(sources_server, vault_dir)
        payload = {
            "type": "auth",
            "operation": "creation",
            "success": False,
            "connectionId": "conn-x",
            "providerConfigKey": "google-drive",
        }
        raw = json.dumps(payload).encode("utf-8")
        r = client.post(
            "/api/v1/sources/webhook",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Nango-Signature": _sign(raw),
            },
        )
        assert r.status_code == 204
        # No source was registered.
        assert not any((sources_root / ".sources").glob("*.json"))

    def test_unsupported_provider_key_ignored(
        self, sources_server, vault_dir, sources_root
    ) -> None:
        client = _client(sources_server, vault_dir)
        payload = {
            "type": "auth",
            "operation": "creation",
            "success": True,
            "connectionId": "conn-x",
            "providerConfigKey": "slack",
            "tags": {},
        }
        raw = json.dumps(payload).encode("utf-8")
        r = client.post(
            "/api/v1/sources/webhook",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Nango-Signature": _sign(raw),
            },
        )
        # Acknowledged (204) but no source created — operator added a
        # Nango integration we don't know about.
        assert r.status_code == 204
        assert not any((sources_root / ".sources").glob("*.json"))

    def test_non_auth_event_skipped(self, sources_server, vault_dir) -> None:
        client = _client(sources_server, vault_dir)
        raw = b'{"type":"sync","operation":"completed"}'
        r = client.post(
            "/api/v1/sources/webhook",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Nango-Signature": _sign(raw),
            },
        )
        assert r.status_code == 204


# --- health ---------------------------------------------------------------


class TestNangoHealth:
    def test_reports_configured_when_client_present(
        self, sources_server, vault_dir
    ) -> None:
        client = _client(sources_server, vault_dir)
        r = client.get("/api/v1/nango/health", headers=USER_HEADER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["configured"] is True

    def test_reports_unconfigured_when_client_missing(
        self, sources_server, vault_dir
    ) -> None:
        client = _client(sources_server, vault_dir, with_nango=False)
        r = client.get("/api/v1/nango/health", headers=USER_HEADER)
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is False
        assert "MEMOGRAPH_NANGO" in (body["last_error"] or "")
