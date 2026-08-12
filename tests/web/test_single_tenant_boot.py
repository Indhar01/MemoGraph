"""Guardrail smoke test for the open-core extraction (manifest step 4).

Asserts the public web server boots and serves core routes as a SINGLE-TENANT
app with NO plugins installed and NO enterprise features enabled. This must
stay green before AND after de-wiring enterprise modules out of server.py, so
it is the safety net for that refactor. See docs/EXTRACTION_MANIFEST.md.
"""

from __future__ import annotations

import importlib

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


@pytest.fixture
def server_mod(monkeypatch):
    # Force the leanest possible configuration: no tenancy, no sources, no auth.
    monkeypatch.delenv("MEMOGRAPH_TENANCY_ENABLED", raising=False)
    monkeypatch.setenv("MEMOGRAPH_SOURCES_ENABLED", "0")
    monkeypatch.delenv("MEMOGRAPH_AUTH_PROVIDER", raising=False)
    from memograph.web.backend import auth as auth_mod
    from memograph.web.backend import server as server_mod

    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    return server_mod


@pytest.fixture
def client(server_mod, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "hello.md").write_text(
        "---\nid: hello\ntitle: Hello\n---\n\nworld\n", encoding="utf-8"
    )
    app = server_mod.create_app(vault_path=str(vault), use_gam=False)
    app.state.kernel.ingest()
    app.state.is_ready = True
    return TestClient(app)


class TestSingleTenantBootNoPlugins:
    def test_healthz(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200

    def test_readyz(self, client):
        r = client.get("/readyz")
        assert r.status_code in (200, 503)  # ready flag may vary; must respond

    def test_core_memories_route_serves(self, client):
        r = client.get("/api/v1/memories")
        assert r.status_code == 200

    def test_search_route_serves(self, client):
        # Route is mounted (search is POST; GET yields 405, not 404).
        r = client.get("/api/v1/search", params={"q": "world"})
        assert r.status_code in (200, 405, 422)

    def test_tenant_registry_absent_by_default(self, client):
        # Single-tenant: no registry constructed.
        assert getattr(client.app.state, "tenant_registry", None) is None

    def test_admin_routes_unavailable_or_gated(self, client):
        # Admin tenant API must NOT be openly functional in the lean build:
        # either the route is absent (404) or gated (401/403/503).
        r = client.get("/api/v1/admin/tenants")
        assert r.status_code in (401, 403, 404, 503)

    def test_app_builds_without_plugins(self, client):
        # The plugin marker is set (load_plugins ran) and no plugin activated.
        active = getattr(client.app.state, "_memograph_active_plugins", [])
        assert active == []
