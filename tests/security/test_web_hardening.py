"""End-to-end behaviour tests for Phase 1.2 web hardening.

Covers request-ID middleware, body-size cap, CORS allowlist, rate
limiter, /healthz vs /readyz semantics, /api/v1 vs legacy /api
deprecation tagging, and the post-Phase-0 info-disclosure stance on
/api/health.

These exercise the assembled app through ``TestClient`` rather than
poking middleware classes directly — the goal is to catch regressions
in middleware ordering or wiring, not just in individual classes.
"""

from __future__ import annotations

import importlib
import os
import re

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


@pytest.fixture
def server_module(monkeypatch: pytest.MonkeyPatch):
    """Reimport the server module under controlled env so module-level
    constants (DEBUG, LOG_JSON) reflect this test's intent."""
    # Ensure tests start with a known-clean env. Individual tests can
    # override before requesting this fixture; we re-import after.
    monkeypatch.delenv("MEMOGRAPH_DEBUG", raising=False)
    monkeypatch.delenv("MEMOGRAPH_LOG_JSON", raising=False)
    monkeypatch.delenv("MEMOGRAPH_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("MEMOGRAPH_MAX_BODY_BYTES", raising=False)
    monkeypatch.delenv("MEMOGRAPH_RATELIMIT_DEFAULT", raising=False)
    monkeypatch.delenv("MEMOGRAPH_RATELIMIT_DISABLED", raising=False)

    from memograph.web.backend import server as server_mod

    return importlib.reload(server_mod)


@pytest.fixture
def vault_dir(tmp_path):
    d = tmp_path / "vault"
    d.mkdir()
    return d


def _make_client(server_module, vault_dir) -> TestClient:
    app = server_module.create_app(vault_path=str(vault_dir), use_gam=False)
    app.state.kernel.ingest()
    app.state.is_ready = True
    return TestClient(app)


class TestRequestId:
    def test_minted_when_absent(self, server_module, vault_dir):
        client = _make_client(server_module, vault_dir)
        r = client.get("/healthz")
        rid = r.headers.get("X-Request-ID")
        assert rid and re.fullmatch(r"[0-9a-f]{32}", rid), rid

    def test_caller_value_echoed(self, server_module, vault_dir):
        client = _make_client(server_module, vault_dir)
        r = client.get("/healthz", headers={"X-Request-ID": "abc-123"})
        assert r.headers["X-Request-ID"] == "abc-123"

    def test_caller_value_replaced_when_too_long(self, server_module, vault_dir):
        client = _make_client(server_module, vault_dir)
        r = client.get("/healthz", headers={"X-Request-ID": "x" * 200})
        # Replaced with a fresh UUID hex, not echoed.
        assert r.headers["X-Request-ID"] != "x" * 200
        assert len(r.headers["X-Request-ID"]) == 32


class TestBodySizeLimit:
    def test_small_body_accepted(self, server_module, vault_dir):
        client = _make_client(server_module, vault_dir)
        # The route may 4xx for other reasons; we only care that the
        # body-size middleware doesn't 413.
        r = client.post("/api/v1/memories", json={"title": "t", "content": "c"})
        assert r.status_code != 413

    def test_oversized_body_rejected(self, monkeypatch, server_module, vault_dir):
        monkeypatch.setenv("MEMOGRAPH_MAX_BODY_BYTES", "100")
        # No need to reimport — middleware reads env at dispatch time.
        client = _make_client(server_module, vault_dir)
        # Fake a request larger than the cap by setting a large
        # Content-Length header. Use a body the server can read but the
        # header tells the middleware is huge.
        big = "a" * 200
        r = client.post(
            "/api/v1/memories",
            data=big,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413
        assert r.json()["code"] == "PAYLOAD_TOO_LARGE"
        assert r.json()["limit_bytes"] == 100

    def test_malformed_content_length_rejected(
        self, monkeypatch, server_module, vault_dir
    ):
        # Skipped on platforms where TestClient drops malformed headers
        # before they reach the middleware. We instantiate the
        # middleware directly to avoid that.
        from memograph.web.backend.middleware import BodySizeLimitMiddleware
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import PlainTextResponse

        async def ok(_):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/", ok, methods=["POST"])])
        app.add_middleware(BodySizeLimitMiddleware)
        client = TestClient(app)
        r = client.post("/", headers={"Content-Length": "not-a-number"})
        assert r.status_code == 400


class TestRateLimit:
    def test_rate_limit_trips(self, monkeypatch, vault_dir):
        monkeypatch.setenv("MEMOGRAPH_RATELIMIT_DEFAULT", "3/minute")
        # Reload BOTH rate_limit (defaults captured at module load)
        # and server (so the new limiter is wired).
        from memograph.web.backend import rate_limit as rate_limit_mod
        from memograph.web.backend import server as server_mod

        importlib.reload(rate_limit_mod)
        importlib.reload(server_mod)
        client = _make_client(server_mod, vault_dir)

        ok_count = 0
        limited = False
        for _ in range(8):
            r = client.get("/api/v1/health")
            if r.status_code == 200:
                ok_count += 1
            elif r.status_code == 429:
                limited = True
                assert r.json()["code"] == "RATE_LIMITED"
                # Retry-After should be present (slowapi sets it).
                # We don't pin the exact value — implementation detail.
                break
        assert limited, f"expected 429 after threshold, got only 200s ({ok_count})"


class TestApiVersioning:
    def test_v1_health_works(self, server_module, vault_dir):
        client = _make_client(server_module, vault_dir)
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"
        assert "Deprecation" not in r.headers

    def test_legacy_health_works_with_deprecation_header(
        self, server_module, vault_dir
    ):
        client = _make_client(server_module, vault_dir)
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.headers.get("Deprecation") == "true"
        assert r.headers.get("Sunset") == "v0.5.0"
        assert "/api/v1/" in r.headers.get("Link", "")


class TestHealthProbes:
    def test_healthz_alive(self, server_module, vault_dir):
        client = _make_client(server_module, vault_dir)
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "alive"}

    def test_readyz_after_ingest(self, server_module, vault_dir):
        client = _make_client(server_module, vault_dir)
        r = client.get("/readyz")
        assert r.status_code == 200
        assert r.json() == {"status": "ready"}

    def test_readyz_returns_503_before_ready(self, server_module, vault_dir):
        app = server_module.create_app(vault_path=str(vault_dir), use_gam=False)
        # Don't ingest — leave is_ready False.
        app.state.is_ready = False
        client = TestClient(app)
        r = client.get("/readyz")
        assert r.status_code == 503
        assert r.json() == {"status": "not_ready"}

    def test_api_health_does_not_leak_vault_path(self, server_module, vault_dir):
        client = _make_client(server_module, vault_dir)
        r = client.get("/api/health")
        body = r.json()
        # /api/health should not leak vault_path absent MEMOGRAPH_DEBUG=1.
        assert "vault_path" not in body, body
        assert "total_memories" not in body, body


class TestCorsAllowlist:
    def test_no_cors_headers_when_unset(self, server_module, vault_dir):
        # MEMOGRAPH_CORS_ORIGINS not set, MEMOGRAPH_DEBUG not set.
        client = _make_client(server_module, vault_dir)
        r = client.get(
            "/api/v1/health",
            headers={"Origin": "https://evil.example"},
        )
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers}

    def test_cors_allowed_when_origin_listed(self, monkeypatch, vault_dir):
        monkeypatch.setenv(
            "MEMOGRAPH_CORS_ORIGINS", "https://app.example,https://admin.example"
        )
        from memograph.web.backend import server as server_mod

        importlib.reload(server_mod)
        client = _make_client(server_mod, vault_dir)

        r = client.get(
            "/api/v1/health",
            headers={"Origin": "https://app.example"},
        )
        assert r.headers.get("access-control-allow-origin") == "https://app.example"

    def test_cors_denied_when_origin_not_listed(self, monkeypatch, vault_dir):
        monkeypatch.setenv("MEMOGRAPH_CORS_ORIGINS", "https://app.example")
        from memograph.web.backend import server as server_mod

        importlib.reload(server_mod)
        client = _make_client(server_mod, vault_dir)

        r = client.get(
            "/api/v1/health",
            headers={"Origin": "https://evil.example"},
        )
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


@pytest.fixture(autouse=True)
def _restore_server_module_after_test():
    """Reload server module after each test so env-driven mutations
    don't leak into siblings."""
    yield
    # Drop env we may have set then reload to a clean baseline.
    for var in (
        "MEMOGRAPH_CORS_ORIGINS",
        "MEMOGRAPH_MAX_BODY_BYTES",
        "MEMOGRAPH_RATELIMIT_DEFAULT",
        "MEMOGRAPH_RATELIMIT_DISABLED",
    ):
        os.environ.pop(var, None)
    from memograph.web.backend import rate_limit as rate_limit_mod
    from memograph.web.backend import server as server_mod

    importlib.reload(rate_limit_mod)
    importlib.reload(server_mod)
