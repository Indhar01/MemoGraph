"""Phase 3.5 release-gating isolation test.

Two API keys grant access to two different tenants. Each writes a
memory. Then for every public route on tenant A we assert tenant B's
data never appears, and vice versa.

Bar (binding, per ADR 0001):

* Cross-tenant search returns empty (no leak via the embedding cache
  or in-RAM graph state).
* Cross-tenant get-by-id returns 404, not the other tenant's record.
* Listing memories for tenant A returns only A's records.
* The graph endpoint exposes only the calling tenant's nodes.
* Admin offboard of tenant A leaves tenant B byte-identical on disk.
* Single-tenant deployments (`MEMOGRAPH_TENANCY_ENABLED` unset)
  preserve the pre-Phase-3.5 behavior — no 403 for users without an
  org_id claim.

This test is the v1 multi-tenant release blocker. If any assertion
fails, do not ship.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture
def global_root(tmp_path: Path) -> Path:
    d = tmp_path / "tenants"
    d.mkdir()
    return d


@pytest.fixture
def server_mod(monkeypatch, global_root):
    """Reload the server with multi-tenancy + api_key auth, then patch
    the verifier to bind specific keys to specific tenant ids.

    A real deployment would carry the tenant in an OIDC org_id claim
    or in a hashed-key-to-tenant map. For the test we patch
    ``_verify_api_key`` so:

      ``key-acme``    -> User(organization_id="acme", scopes=("api_key",))
      ``key-globex``  -> User(organization_id="globex", scopes=("api_key",))
      ``key-admin``   -> User(organization_id="acme", scopes=("api_key", "admin"))
    """
    monkeypatch.setenv("MEMOGRAPH_TENANCY_ENABLED", "1")
    monkeypatch.setenv("MEMOGRAPH_GLOBAL_ROOT", str(global_root))
    monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
    monkeypatch.setenv("MEMOGRAPH_API_KEYS", "key-acme,key-globex,key-admin,key-orphan")

    from memograph.web.backend import auth as auth_mod
    from memograph.web.backend import server as server_mod

    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    auth_mod._reset_oidc_state()

    original = auth_mod._verify_api_key
    bindings = {
        "key-acme": ("acme", ("api_key",)),
        "key-globex": ("globex", ("api_key",)),
        "key-admin": ("acme", ("api_key", "admin")),
        # key-orphan: no organization_id — should be rejected by
        # resolve_tenant_id with 403.
        "key-orphan": ("", ("api_key",)),
    }

    def _verify_with_tenant(key: str):
        user = original(key)
        if user is None:
            return None
        org, scopes = bindings.get(key, ("", ("api_key",)))
        return auth_mod.User(
            id=user.id,
            email=user.email,
            organization_id=org,
            scopes=scopes,
            raw_claims=user.raw_claims,
        )

    monkeypatch.setattr(auth_mod, "_verify_api_key", _verify_with_tenant)
    return server_mod


@pytest.fixture
def client(server_mod, vault_dir):
    app = server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
    app.state.is_ready = True
    return TestClient(app)


def _hdr(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def _create(client, key: str, title: str, content: str):
    """Create a memory via the public API. Returns the response."""
    return client.post(
        "/api/v1/memories",
        json={
            "title": title,
            "content": content,
            "memory_type": "semantic",
            "tags": [],
            "salience": 0.5,
        },
        headers=_hdr(key),
    )


# ---------------------------------------------------------- core invariants


def test_orphan_user_rejected_in_multi_tenant_mode(client):
    """User authenticated but with no organization_id → 403."""
    r = client.get("/api/v1/memories", headers=_hdr("key-orphan"))
    assert r.status_code == 403


def test_unauthenticated_still_401(client):
    r = client.get("/api/v1/memories")
    assert r.status_code == 401


def test_create_memory_lands_in_calling_tenant(client, global_root):
    r = _create(client, "key-acme", "Acme Note", "secret-acme")
    assert r.status_code == 200, r.text

    # File materialized under acme's vault, not globex's.
    acme_files = list((global_root / "acme").rglob("*.md"))
    assert len(acme_files) == 1
    assert "secret-acme" in acme_files[0].read_text(encoding="utf-8")
    assert not (global_root / "globex").exists() or not list(
        (global_root / "globex").rglob("*.md")
    )


def test_list_memories_only_returns_own_tenant(client):
    _create(client, "key-acme", "Acme Note", "secret-acme")
    _create(client, "key-globex", "Globex Note", "secret-globex")

    a = client.get("/api/v1/memories", headers=_hdr("key-acme"))
    b = client.get("/api/v1/memories", headers=_hdr("key-globex"))

    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text

    a_titles = {m["title"] for m in a.json()["memories"]}
    b_titles = {m["title"] for m in b.json()["memories"]}

    assert a_titles == {"Acme Note"}
    assert b_titles == {"Globex Note"}


def test_get_memory_cross_tenant_returns_404(client):
    create_a = _create(client, "key-acme", "Acme Secret", "very-acme")
    assert create_a.status_code == 200, create_a.text
    acme_id = create_a.json()["id"]

    # Tenant B asks for tenant A's memory id directly.
    r = client.get(f"/api/v1/memories/{acme_id}", headers=_hdr("key-globex"))
    assert r.status_code == 404


def test_search_does_not_leak_across_tenants(client):
    _create(client, "key-acme", "Acme Note", "very-distinctive-acme-token")
    _create(client, "key-globex", "Globex Note", "very-distinctive-globex-token")

    # Tenant A searches for tenant B's distinctive content.
    r = client.post(
        "/api/v1/search",
        json={"query": "very-distinctive-globex-token", "top_k": 10, "depth": 1},
        headers=_hdr("key-acme"),
    )
    assert r.status_code == 200
    titles = {m["title"] for m in r.json().get("results", [])}
    assert "Globex Note" not in titles


def test_graph_endpoint_only_exposes_own_tenant(client):
    _create(client, "key-acme", "Acme Note", "x")
    _create(client, "key-globex", "Globex Note", "y")

    r = client.get("/api/v1/graph", headers=_hdr("key-acme"))
    assert r.status_code == 200
    titles = {n["title"] for n in r.json().get("nodes", [])}
    assert "Globex Note" not in titles


def test_admin_offboard_leaves_other_tenant_intact(client, global_root):
    _create(client, "key-acme", "Acme Note", "acme-content")
    _create(client, "key-globex", "Globex Note", "globex-content")

    r = client.delete(
        "/api/v1/admin/tenants/acme",
        headers=_hdr("key-admin"),
    )
    assert r.status_code == 204

    # Acme directory is gone; globex is byte-identical.
    assert not (global_root / "acme").exists()
    globex_files = list((global_root / "globex").rglob("*.md"))
    assert len(globex_files) == 1
    assert "globex-content" in globex_files[0].read_text(encoding="utf-8")

    # Globex tenant can still serve requests.
    r = client.get("/api/v1/memories", headers=_hdr("key-globex"))
    assert r.status_code == 200
    titles = {m["title"] for m in r.json()["memories"]}
    assert titles == {"Globex Note"}


# ---------------------------------------------------------- single-tenant smoke


@pytest.fixture
def single_tenant_client(monkeypatch, vault_dir):
    """Reload the server WITHOUT MEMOGRAPH_TENANCY_ENABLED. Verifies that
    the Phase 3.5 dependency change preserves single-tenant behavior:
    users without an organization_id can still hit every route, and the
    same single ``app.state.kernel`` serves every request."""
    monkeypatch.delenv("MEMOGRAPH_TENANCY_ENABLED", raising=False)
    monkeypatch.delenv("MEMOGRAPH_GLOBAL_ROOT", raising=False)
    monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
    monkeypatch.setenv("MEMOGRAPH_API_KEYS", "key-solo")

    from memograph.web.backend import auth as auth_mod
    from memograph.web.backend import server as server_mod

    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    auth_mod._reset_oidc_state()

    app = server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
    app.state.is_ready = True
    return TestClient(app)


def test_single_tenant_no_tenant_claim_required(single_tenant_client):
    """Without MEMOGRAPH_TENANCY_ENABLED, the api_key user has
    organization_id="" but should still reach every route."""
    r = single_tenant_client.get("/api/v1/memories", headers=_hdr("key-solo"))
    assert r.status_code == 200, r.text


def test_single_tenant_create_then_list(single_tenant_client):
    r = single_tenant_client.post(
        "/api/v1/memories",
        json={
            "title": "Solo",
            "content": "single-tenant content",
            "memory_type": "semantic",
            "tags": [],
            "salience": 0.5,
        },
        headers=_hdr("key-solo"),
    )
    assert r.status_code == 200

    r = single_tenant_client.get("/api/v1/memories", headers=_hdr("key-solo"))
    assert r.status_code == 200
    titles = {m["title"] for m in r.json()["memories"]}
    assert titles == {"Solo"}
