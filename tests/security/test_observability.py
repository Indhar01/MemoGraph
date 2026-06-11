"""Tests for the Phase 2.1 observability hooks.

The OTel exporter is not exercised end-to-end (would need a collector);
we verify only that ``init_telemetry`` is a safe no-op when env vars
are unset and that the Prometheus ``/metrics`` endpoint exposes the
expected metric names with the correct label cardinality.
"""

from __future__ import annotations

import importlib

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


@pytest.fixture
def vault_dir(tmp_path):
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def _reset_observability_state():
    """Drop the module-level init flags + Prometheus registry between
    tests so re-imports don't trip duplicate-metric errors."""
    from memograph.web.backend import observability

    observability.reset_for_tests()
    yield
    observability.reset_for_tests()


def _client_with_metrics(monkeypatch, vault_dir) -> TestClient:
    monkeypatch.setenv("MEMOGRAPH_METRICS_ENABLED", "1")
    from memograph.web.backend import observability
    from memograph.web.backend import server as server_mod

    importlib.reload(observability)
    importlib.reload(server_mod)
    observability.reset_for_tests()
    app = server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
    app.state.kernel.ingest()
    app.state.is_ready = True
    return TestClient(app)


class TestPrometheusMetrics:
    def test_metrics_disabled_by_default(self, vault_dir):
        from memograph.web.backend import server as server_mod

        importlib.reload(server_mod)
        app = server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
        client = TestClient(app)
        r = client.get("/metrics")
        # 404 because the route isn't registered when the env flag is off.
        assert r.status_code == 404

    def test_metrics_enabled_exposes_counters(self, monkeypatch, vault_dir):
        client = _client_with_metrics(monkeypatch, vault_dir)
        # Drive a couple of requests so counters have something to report.
        client.get("/healthz")
        client.get("/healthz")
        r = client.get("/metrics")
        assert r.status_code == 200
        body = r.text
        assert "memograph_http_requests_total" in body
        assert "memograph_http_request_duration_seconds" in body
        # Content type honors Prometheus exposition format.
        assert "text/plain" in r.headers["content-type"]

    def test_route_template_used_for_label(self, monkeypatch, vault_dir):
        """Path-parameter routes must use the *template* as the label;
        otherwise high-cardinality memory IDs explode the metric set."""
        monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
        monkeypatch.setenv("MEMOGRAPH_API_KEYS", "metrics-key")
        client = _client_with_metrics(monkeypatch, vault_dir)
        # Two GETs against /api/v1/memories/{id} with different ids.
        # Even if the IDs 404 (memory doesn't exist), the metric label
        # should collapse them into one counter.
        for mid in ("aaa", "bbb", "ccc"):
            client.get(
                f"/api/v1/memories/{mid}",
                headers={"X-API-Key": "metrics-key"},
            )
        body = client.get("/metrics", headers={"X-API-Key": "metrics-key"}).text
        # The metric line should mention the templated path, not the
        # concrete IDs.
        assert "/api/v1/memories/{memory_id}" in body
        assert "aaa" not in body
        assert "bbb" not in body


class TestOtelInitNoop:
    def test_init_without_endpoint_is_silent(self, vault_dir, caplog):
        """No env vars set → no OTel SDK init, no warning, no crash."""
        import logging

        from memograph.web.backend import server as server_mod

        importlib.reload(server_mod)
        with caplog.at_level(logging.WARNING):
            server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
        assert not any("OpenTelemetry" in rec.message for rec in caplog.records)
