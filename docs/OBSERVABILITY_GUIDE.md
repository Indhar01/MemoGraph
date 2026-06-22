# Observability guide

MemoGraph emits enough signal for an operator to answer two
questions without SSHing into the box:

1. *Is it healthy?* — liveness, readiness, error rate.
2. *Why is it slow?* — per-route latency, kernel op latency,
   embedding cache hit ratio, swarm cycle duration.

This document walks through what's emitted, where to point your
collectors, and what dashboards to build.

## Endpoints

| Endpoint | Purpose | Auth |
|---|---|---|
| `/healthz` | Liveness. Returns 200 if the process is up. | none |
| `/readyz` | Readiness. Returns 200 only after the kernel has finished initial ingest. | none |
| `/metrics` | Prometheus exposition (when `MEMOGRAPH_METRICS_ENABLED=1`). | none — block at the proxy from the public internet |
| `/api/v1/auth/me` | Lets monitoring confirm token validity. | yes |

`/healthz` and `/readyz` are split intentionally. A k8s liveness
probe wants `/healthz` (the process is responsive); a k8s readiness
probe wants `/readyz` (the process is ready to serve traffic). If
you collapse them into one, an unhealthy ingest will get the pod
killed and re-killed forever.

## Prometheus

Set `MEMOGRAPH_METRICS_ENABLED=1` and scrape `/metrics`. The metrics
the server exposes:

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `memograph_request_duration_seconds` | histogram | `route`, `method`, `status` | End-to-end request latency. Histogram buckets default to Prometheus standard. |
| `memograph_request_total` | counter | `route`, `method`, `status` | Request count. |
| `memograph_kernel_op_duration_seconds` | histogram | `op` (`remember`/`search`/`ingest`/etc.) | Kernel-level latency, useful when API latency includes both kernel work and middleware. |
| `memograph_vault_size_bytes` | gauge | (none in v1.0; will gain `tenant_id` when Phase 3.5 lands) | On-disk size of the vault root. |
| `memograph_embedding_cache_hits_total` | counter | (none) | Cache hit count. |
| `memograph_embedding_cache_misses_total` | counter | (none) | Cache miss count. |

Cardinality discipline:

- The `route` label uses the *route template* (e.g.
  `/api/v1/memories/{memory_id}`), not the concrete URL. Memory ids
  in URLs would explode the label space.
- We do not (yet) emit `tenant_id`-labelled metrics. That changes
  in Phase 3.5; before we ship that, set up an alert on metric
  count growth so a tenant explosion doesn't OOM your Prometheus.

## OpenTelemetry

When the `observability` extra is installed and the standard OTel
env vars are set, MemoGraph auto-instruments:

- FastAPI (every request becomes a span).
- The HTTP outgoing client used by integrations.
- Manual spans on `kernel.search`, `kernel.remember`, `ingest`,
  and per-agent `swarm` cycles.

```bash
OTEL_SERVICE_NAME=memograph
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=https://otel-collector.example.com:4318
OTEL_EXPORTER_OTLP_HEADERS=authorization=Bearer%20<token>
```

Common backends:

- **Honeycomb**: set `OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io`
  and `OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<key>`.
- **Grafana Cloud**: use their OTLP gateway.
- **Datadog**: set `OTEL_EXPORTER_OTLP_HEADERS=DD-API-KEY=<key>`.
- **Self-hosted Tempo / Jaeger**: set the OTLP endpoint to your
  collector.

## Structured logs

Set `MEMOGRAPH_LOG_JSON=1` and pipe logs to your aggregator. Every
log line carries:

- `ts` (UTC ISO-8601)
- `level` (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- `name` (logger name)
- `message`
- `request_id` (when in a request context — propagated via the
  `RequestIdMiddleware`)

Index `request_id` in your log aggregator. It lets you pivot from a
slow span in your trace UI to all log lines for that request.

## Dashboards

A solid first dashboard has six panels:

1. **Request rate (per route)** — line chart of
   `rate(memograph_request_total[1m])` grouped by `route`.
2. **Error rate (per route)** — line chart of
   `rate(memograph_request_total{status=~"5.."}[1m])` grouped by
   `route`. Alert when it crosses your SLO.
3. **p95 latency (per route)** — heatmap of
   `histogram_quantile(0.95, sum by (le, route)
   (rate(memograph_request_duration_seconds_bucket[5m])))`.
4. **Kernel op latency** — same shape, grouped by `op`.
5. **Embedding cache hit ratio** —
   `rate(memograph_embedding_cache_hits_total[5m]) /
   (rate(memograph_embedding_cache_hits_total[5m]) +
    rate(memograph_embedding_cache_misses_total[5m]))`.
   Aim for >0.9 in steady state.
6. **Vault size growth** — `memograph_vault_size_bytes` over time.
   Useful for forecasting storage and quota tuning.

## Alerts

Start with these four:

| Alert | Condition | Page when |
|---|---|---|
| API down | `up{job="memograph"} == 0` for 2m | Always |
| Error rate spike | 5xx ratio > 1% for 5m | Always |
| Slow ingest | `/readyz` returning non-200 for 10m | Always |
| Cache hit ratio drop | hit ratio < 0.5 for 30m | Daytime only — usually a model swap |

Avoid alerting on individual high-latency requests; use the
histogram p95/p99. A single slow request is normal; a sustained
shift in p95 is a pageable event.

## Audit log

Telemetry above is for *operators*. The audit log is for
*compliance*: every mutation writes an `Action` record (see
`memograph/core/action_logger.py`).

- Stored as JSONL inside the vault under `audit/`.
- One file per day; rotates without external triggers.
- Each record has `user`, `tenant_id`, `verb`, `target`,
  `timestamp`, `outcome`.

Ship the audit log to your SIEM if you have compliance obligations
(SOC 2 access reviews, GDPR DPA evidence). The
`COMPLIANCE_ROADMAP.md` doc covers the controls SOC 2 wants you to
attach to this log.

## Troubleshooting

**The /readyz endpoint stays at 503.**

- Check the API logs for an ingestion error. The kernel keeps the
  last error on `_last_ingest_error`; the log line will be `ERROR`.
- Most common cause: corrupt YAML frontmatter on a single file.
  The parser logs the offending file and continues; if a different
  failure mode is masking ready-state, that's a bug — file an issue.

**p95 latency suddenly doubled.**

- Pull the trace for a slow request. The kernel-op span tells you
  if it's search, remember, or middleware.
- If `embedding_cache_misses_total` suddenly spiked, somebody
  blew the cache (deploy, model change, schema migration).
- If kernel-op latency is flat but request latency is up, look at
  middleware (rate limiter under contention, GZip on huge bodies).

**The `/metrics` endpoint is empty.**

- `MEMOGRAPH_METRICS_ENABLED` is unset.
- Or the Prometheus client wasn't installed (only ships with the
  `[observability]` extra).
