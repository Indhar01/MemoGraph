"""OpenTelemetry traces/metrics and Prometheus ``/metrics`` exposition.

This module is opt-in: nothing fires unless the operator either installs
the ``[observability]`` extra and sets ``MEMOGRAPH_OTEL_EXPORTER_ENDPOINT``
(for OTLP) or sets ``MEMOGRAPH_METRICS_ENABLED=1`` (for Prometheus
exposition). Both can run together — Prometheus scrapes `/metrics`, OTel
ships to a collector. The base ``[web]`` install stays lightweight.

Configuration env vars
----------------------

``MEMOGRAPH_METRICS_ENABLED``
    "1"/"true"/"yes" exposes a Prometheus ``/metrics`` endpoint.
    Defaults off — production deployments behind a metrics-aware
    reverse proxy (Grafana Agent, OTel collector) should set this.

``MEMOGRAPH_OTEL_EXPORTER_ENDPOINT``
    OTLP/HTTP endpoint URL (e.g. ``https://otlp.example/v1/traces``).
    Setting this enables tracing + metrics export via OTLP. We use the
    HTTP/protobuf exporter because gRPC adds another transitive
    dependency and the throughput difference is negligible at the
    scales MemoGraph runs at.

``MEMOGRAPH_OTEL_SERVICE_NAME``
    Resource ``service.name`` attribute. Defaults to "memograph".

``MEMOGRAPH_OTEL_HEADERS``
    Comma-separated ``k=v`` pairs sent on every OTLP request. Used for
    backend auth (e.g. Honeycomb's ``x-honeycomb-team``).

The module exports two helpers used by ``server.py``:

- :func:`init_telemetry(app)` — wires both exporters if configured;
  no-op otherwise.
- :func:`metrics_endpoint(request)` — Prometheus exposition handler.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.responses import Response

logger = logging.getLogger(__name__)


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes"}


# Prometheus metrics are module-level so they survive create_app reloads
# in tests; calling _build_prometheus_metrics() twice on the same registry
# would error otherwise. Lazy-init guarded by _prom_initialised.
_prom_initialised = False
_request_counter: Any = None
_request_duration: Any = None
_kernel_op_duration: Any = None
# Source-adapter metrics (Phase 1+ of ADR 0002 implementation).
# Registered alongside the existing request/kernel metrics so a single
# /metrics scrape exposes everything an operator needs to chart source
# behavior against request latency.
_source_sync_counter: Any = None
_source_sync_duration: Any = None
_source_documents_gauge: Any = None
_source_swap_counter: Any = None
_source_health_gauge: Any = None


def _build_prometheus_metrics() -> None:
    """Idempotent registration of MemoGraph metrics on the default registry."""
    global _prom_initialised, _request_counter, _request_duration, _kernel_op_duration
    global _source_sync_counter, _source_sync_duration, _source_documents_gauge
    global _source_swap_counter, _source_health_gauge
    if _prom_initialised:
        return
    try:
        from prometheus_client import Counter, Gauge, Histogram
    except ImportError:
        logger.info(
            "prometheus_client not installed; /metrics endpoint will be empty. "
            "pip install memograph[observability] to enable."
        )
        return

    _request_counter = Counter(
        "memograph_http_requests_total",
        "Count of HTTP requests by route, method, and status",
        ("route", "method", "status"),
    )
    _request_duration = Histogram(
        "memograph_http_request_duration_seconds",
        "HTTP request handling latency",
        ("route", "method"),
        # Buckets tuned for typical kernel.search latency (sub-100ms hot,
        # up to a few seconds for cold ingest paths).
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    _kernel_op_duration = Histogram(
        "memograph_kernel_op_duration_seconds",
        "MemoryKernel operation latency",
        ("op",),
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0),
    )
    # ---- Source-adapter metrics (ADR 0002 v1.1+) ----
    _source_sync_counter = Counter(
        "memograph_source_sync_total",
        "Source sync attempts by tenant, kind, and outcome",
        ("tenant", "source_kind", "result"),
    )
    _source_sync_duration = Histogram(
        "memograph_source_sync_duration_seconds",
        "Source sync wall-clock duration",
        ("source_kind",),
        # Sources can sync seconds (local mtime walk) to minutes (large
        # Drive folder cold pull). Buckets cover both regimes.
        buckets=(0.05, 0.25, 1.0, 5.0, 15.0, 60.0, 300.0, 900.0),
    )
    _source_documents_gauge = Gauge(
        "memograph_source_documents_total",
        "Document count per source as of the last successful sync",
        ("tenant", "source_kind"),
    )
    _source_swap_counter = Counter(
        "memograph_source_swap_total",
        "Active-source swap attempts by tenant, from_kind, to_kind, result",
        ("tenant", "from_kind", "to_kind", "result"),
    )
    _source_health_gauge = Gauge(
        "memograph_source_health",
        "Source health: 0=failed, 1=degraded, 2=ok",
        ("tenant", "source_kind"),
    )
    _prom_initialised = True


def record_request(
    route: str, method: str, status: int, duration_seconds: float
) -> None:
    """Record a single request into Prometheus metrics. No-op if disabled."""
    _build_prometheus_metrics()
    if _request_counter is None:
        return
    _request_counter.labels(route=route, method=method, status=str(status)).inc()
    _request_duration.labels(route=route, method=method).observe(duration_seconds)


def record_kernel_op(op: str, duration_seconds: float) -> None:
    """Record a kernel operation latency. No-op if disabled."""
    _build_prometheus_metrics()
    if _kernel_op_duration is None:
        return
    _kernel_op_duration.labels(op=op).observe(duration_seconds)


# --- Source-adapter recording helpers (ADR 0002 v1.1+) ---------------------

# Labels are bucketed before recording to avoid cardinality blowup: a
# single global tenant pseudo-id ("__single__") is used when tenancy is
# disabled. Operators with high tenant counts should aggregate at the
# Prometheus side rather than per-tenant labels — but the label exists
# so a small-multi-tenant deployment can chart individual tenants.

_TENANCY_FALLBACK = "__single__"


def _tenant_label(tenant_id: str | None) -> str:
    return tenant_id if tenant_id else _TENANCY_FALLBACK


def record_source_sync(
    tenant_id: str | None,
    source_kind: str,
    result: str,
    duration_seconds: float,
) -> None:
    """Record one source sync attempt + its duration. No-op if disabled.

    ``result`` is a stable enum string: ``ok`` | ``failed`` |
    ``auth_required`` | ``conflict``. Histograms only see the
    duration; the counter labels capture the result.
    """
    _build_prometheus_metrics()
    if _source_sync_counter is None:
        return
    _source_sync_counter.labels(
        tenant=_tenant_label(tenant_id),
        source_kind=source_kind,
        result=result,
    ).inc()
    _source_sync_duration.labels(source_kind=source_kind).observe(duration_seconds)


def record_source_documents(
    tenant_id: str | None,
    source_kind: str,
    documents: int,
) -> None:
    """Set the document-count gauge for a source. No-op if disabled."""
    _build_prometheus_metrics()
    if _source_documents_gauge is None:
        return
    _source_documents_gauge.labels(
        tenant=_tenant_label(tenant_id),
        source_kind=source_kind,
    ).set(documents)


def record_source_swap(
    tenant_id: str | None,
    from_kind: str | None,
    to_kind: str,
    result: str,
) -> None:
    """Record an active-source swap. ``from_kind`` is empty on first activation."""
    _build_prometheus_metrics()
    if _source_swap_counter is None:
        return
    _source_swap_counter.labels(
        tenant=_tenant_label(tenant_id),
        from_kind=from_kind or "",
        to_kind=to_kind,
        result=result,
    ).inc()


def record_source_health(
    tenant_id: str | None,
    source_kind: str,
    numeric_status: int,
) -> None:
    """Set the health gauge (0=failed, 1=degraded, 2=ok)."""
    _build_prometheus_metrics()
    if _source_health_gauge is None:
        return
    _source_health_gauge.labels(
        tenant=_tenant_label(tenant_id),
        source_kind=source_kind,
    ).set(numeric_status)


def metrics_endpoint() -> Response:
    """Prometheus exposition. Returns 503 if prometheus_client is unavailable."""
    from fastapi.responses import Response

    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    except ImportError:
        return Response(
            content="prometheus_client not installed",
            status_code=503,
            media_type="text/plain",
        )
    _build_prometheus_metrics()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _otel_headers() -> dict[str, str]:
    raw = os.environ.get("MEMOGRAPH_OTEL_HEADERS", "").strip()
    if not raw:
        return {}
    out: dict[str, str] = {}
    for kv in raw.split(","):
        if "=" not in kv:
            continue
        k, _, v = kv.partition("=")
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out


_otel_initialised = False


def init_telemetry(app: FastAPI) -> None:
    """Wire OpenTelemetry tracing + metrics if configured.

    Safe to call multiple times — guards on a module flag so ``importlib.reload``
    in tests doesn't double-instrument FastAPI (which would make every request
    create two spans).
    """
    global _otel_initialised
    endpoint = os.environ.get("MEMOGRAPH_OTEL_EXPORTER_ENDPOINT", "").strip()
    if not endpoint:
        return
    if _otel_initialised:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "MEMOGRAPH_OTEL_EXPORTER_ENDPOINT is set but opentelemetry SDK "
            "is not installed; install memograph[observability] to enable."
        )
        return

    service_name = os.environ.get("MEMOGRAPH_OTEL_SERVICE_NAME", "memograph")
    headers = _otel_headers()

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers or None)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Excluded paths: probe endpoints generate trace spam in steady state.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")

    _otel_initialised = True
    logger.info(
        "OpenTelemetry initialised: endpoint=%s service=%s", endpoint, service_name
    )


def reset_for_tests() -> None:
    """Test helper: drop the OTel and Prometheus init flags."""
    global _otel_initialised, _prom_initialised
    _otel_initialised = False
    _prom_initialised = False
    # Clear the prometheus default registry so re-init doesn't error on
    # duplicate metrics. Best-effort — older clients may not expose the API.
    try:
        from prometheus_client import REGISTRY

        for collector in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(collector)
            except Exception:  # pragma: no cover
                pass
    except ImportError:
        pass
    global _request_counter, _request_duration, _kernel_op_duration
    global _source_sync_counter, _source_sync_duration, _source_documents_gauge
    global _source_swap_counter, _source_health_gauge
    _request_counter = None
    _request_duration = None
    _kernel_op_duration = None
    _source_sync_counter = None
    _source_sync_duration = None
    _source_documents_gauge = None
    _source_swap_counter = None
    _source_health_gauge = None


__all__ = [
    "init_telemetry",
    "metrics_endpoint",
    "record_request",
    "record_kernel_op",
    "record_source_sync",
    "record_source_documents",
    "record_source_swap",
    "record_source_health",
    "reset_for_tests",
]
