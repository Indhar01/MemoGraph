"""FastAPI server for MemoGraph web UI."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from ...core.kernel import MemoryKernel
from .auth import AuthProvider, require_scope, require_user
from .middleware import BodySizeLimitMiddleware, RequestIdMiddleware
from .observability import init_telemetry, metrics_endpoint, record_request
from .rate_limit import limiter, rate_limit_exceeded_handler

_METRICS_ENABLED = os.environ.get("MEMOGRAPH_METRICS_ENABLED", "").lower() in {
    "1",
    "true",
    "yes",
}

# When MEMOGRAPH_DEBUG=1, the 500 handler echoes the exception string and
# /api/health returns the vault path. In production this leaks internals
# to clients; default off, opt-in for local debugging only.
_DEBUG_ENABLED = os.environ.get("MEMOGRAPH_DEBUG", "").lower() in {"1", "true", "yes"}

# When MEMOGRAPH_LOG_JSON=1, switch the root logger to a structured JSON
# formatter (request_id is propagated via the RequestIdMiddleware on the
# request scope; access-log JSON shipping is the operator's job).
_LOG_JSON = os.environ.get("MEMOGRAPH_LOG_JSON", "").lower() in {"1", "true", "yes"}

# Phase 3 multi-tenancy gate. When MEMOGRAPH_TENANCY_ENABLED=1, the server
# constructs a TenantRegistry rooted at MEMOGRAPH_GLOBAL_ROOT (or the
# vault path if unset, treated as the global root) and mounts the admin
# router. Default off — single-tenant deployments need no registry and
# the admin routes 503 cleanly until the operator opts in.
_TENANCY_ENABLED = os.environ.get("MEMOGRAPH_TENANCY_ENABLED", "").lower() in {
    "1",
    "true",
    "yes",
}


def _configure_logging() -> None:
    """Idempotent root-logger setup honoring the LOG_JSON env flag."""
    root = logging.getLogger()
    root.setLevel(os.environ.get("MEMOGRAPH_LOG_LEVEL", "INFO"))

    # Replace any pre-existing handler so a reimport doesn't double-log.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    if _LOG_JSON:
        try:
            from pythonjsonlogger.json import JsonFormatter

            handler.setFormatter(
                JsonFormatter(
                    "%(asctime)s %(name)s %(levelname)s %(message)s",
                    rename_fields={"asctime": "ts", "levelname": "level"},
                )
            )
        except ImportError:
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
            )
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
    root.addHandler(handler)


_configure_logging()
logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Read an env var as an int; fall back to default on garbage."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%r; using default %d", name, raw, default)
        return default


def _cors_origins() -> list[str]:
    """Resolve the CORS allowlist.

    Reads ``MEMOGRAPH_CORS_ORIGINS`` (comma-separated). Falls back to a
    safe local-dev allowlist *only* if MEMOGRAPH_DEBUG=1, so production
    deployments without an explicit allowlist deny all cross-origin
    requests by default rather than silently allowing localhost.
    """
    raw = os.environ.get("MEMOGRAPH_CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if _DEBUG_ENABLED:
        return [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:5173",  # Vite dev server
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
    return []


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    logger.info("Starting MemoGraph server...")
    app.state.is_ready = False
    # Startup: ingest vaults if not already done.
    #
    # Single-tenant mode: ingest the one process-wide kernel.
    # Multi-tenant mode: warm + ingest each tenant whose directory
    # already exists on disk. Tenants created at runtime via the admin
    # API will be ingested lazily by their first request through
    # ``kernel_for_request`` (the registry's factory builds a kernel
    # whose constructor scans the vault).
    try:
        registry = getattr(app.state, "tenant_registry", None)
        if registry is not None:
            known = registry.known_tenants()
            logger.info(f"Multi-tenancy enabled; warming {len(known)} tenants")
            for tid in known:
                kernel = registry.for_tenant(tid)
                stats = await kernel.ingest_async(force=False)
                logger.info(f"Tenant {tid}: ingested {stats['total']} memories")
        elif app.state.kernel:
            logger.info("Ingesting vault on startup...")
            stats = await app.state.kernel.ingest_async(force=False)
            logger.info(f"Vault ingested: {stats['total']} memories loaded")
        app.state.is_ready = True
    except Exception as e:
        logger.error(f"Failed to ingest vault on startup: {e}")
        # Leave is_ready=False so /readyz signals not-ready; the process
        # itself stays up so /healthz still returns 200 (the orchestrator
        # can decide whether to restart).

    yield

    # Shutdown
    app.state.is_ready = False
    logger.info("Shutting down MemoGraph server...")


def create_app(vault_path: str, use_gam: bool = True) -> FastAPI:
    """Create and configure the FastAPI application."""
    provider = AuthProvider.from_env()
    if provider is AuthProvider.NONE:
        logger.warning(
            "Starting MemoGraph with MEMOGRAPH_AUTH_PROVIDER=none. The API "
            "is open. Set MEMOGRAPH_AUTH_PROVIDER=oidc|api_key|multi for "
            "production deployments."
        )
    else:
        logger.info("Auth provider: %s", provider.value)

    app = FastAPI(
        title="MemoGraph API",
        version="1.0.0",
        description="Production-ready API for MemoGraph memory management system",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # Order matters: BodySizeLimit runs first so oversized bodies don't get
    # processed downstream; RequestId next so its value is on scope before
    # any other middleware logs; CORS, rate limit, gzip after. Starlette
    # applies middleware in reverse-add order, so add them in reverse here.
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Rate limiter wiring: state, exception handler, and the middleware
    # that actually enforces default_limits on every route. Without
    # SlowAPIMiddleware, default_limits are inert (they apply only to
    # routes decorated explicitly with @limiter.limit(...)).
    app.state.limiter = limiter
    # Starlette types the handler arg as Exception; slowapi's signature is
    # already correct at runtime — narrowing happens via the dispatch table.
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    cors_origins = _cors_origins()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            allow_headers=["*"],
        )
    else:
        logger.info(
            "CORS allowlist is empty (set MEMOGRAPH_CORS_ORIGINS to enable "
            "cross-origin requests in production)."
        )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)

    # Initialize kernel
    vault_path_obj = Path(vault_path).expanduser()
    logger.info(f"Initializing kernel with vault: {vault_path_obj}")

    kernel = MemoryKernel(vault_path=str(vault_path_obj), use_gam=use_gam)

    app.state.kernel = kernel
    app.state.vault_path = str(vault_path_obj)
    app.state.use_gam = use_gam
    app.state.is_ready = False

    # Phase 3 multi-tenancy: build a registry that materializes one
    # MemoryKernel per tenant under the global root. The single-tenant
    # `kernel` above remains in place during the v0.x → v1.0 transition;
    # the registry is opt-in via MEMOGRAPH_TENANCY_ENABLED. When disabled,
    # admin routes are still mounted but return 503 (see admin._registry).
    app.state.tenant_registry = None
    if _TENANCY_ENABLED:
        from ...core.tenant_registry import TenantRegistry
        from ...storage.tenant_storage import TenantStorage

        global_root = os.environ.get("MEMOGRAPH_GLOBAL_ROOT", str(vault_path_obj))

        def _kernel_factory(tenant_vault_path: str) -> MemoryKernel:
            return MemoryKernel(vault_path=tenant_vault_path, use_gam=use_gam)

        max_warm = _env_int("MEMOGRAPH_TENANT_MAX_WARM", 64)
        app.state.tenant_registry = TenantRegistry(
            storage=TenantStorage(global_root=global_root),
            kernel_factory=_kernel_factory,
            max_warm=max_warm,
        )
        logger.info(
            "Multi-tenancy enabled: global_root=%s max_warm=%d",
            global_root,
            max_warm,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "code": f"HTTP_{exc.status_code}",
            },
            # Forward headers the route attached (e.g. WWW-Authenticate
            # on a 401, Retry-After on a 503). Without this, auth
            # challenges silently lose their auth scheme.
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        # Always log full traceback server-side; never leak it to the client
        # in production. Debug builds (MEMOGRAPH_DEBUG=1) echo the string for
        # local diagnosis only.
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        body: dict[str, str] = {
            "error": "Internal server error",
            "code": "INTERNAL_ERROR",
        }
        if _DEBUG_ENABLED:
            body["detail"] = str(exc)
        return JSONResponse(status_code=500, content=body)

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        """Stamp X-Process-Time on every response, tag legacy /api/ paths,
        and feed Prometheus per-request metrics if enabled."""
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = f"{process_time:.6f}"
        # Routes mounted under the legacy unversioned /api/ prefix get a
        # deprecation header so clients can migrate before the prefix is
        # removed in a future release.
        path = request.url.path
        if path.startswith("/api/") and not path.startswith("/api/v1/"):
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = "v0.5.0"
            response.headers["Link"] = '</api/v1/>; rel="successor-version"'
        # Use the route's path *template* (e.g. "/api/v1/memories/{memory_id}")
        # rather than the concrete URL so memory_id values don't explode the
        # cardinality of the Prometheus label set.
        if _METRICS_ENABLED:
            route = getattr(request.scope.get("route"), "path", path)
            record_request(
                route=route,
                method=request.method,
                status=response.status_code,
                duration_seconds=process_time,
            )
        return response

    # Import and register routes. Mount under both /api/v1/ (canonical
    # going forward) and /api/ (legacy, kept for back-compat with existing
    # callers; flagged with the deprecation header above).
    #
    # Every protected router gets ``Depends(require_user)`` applied at
    # mount time so individual route bodies don't have to remember. When
    # MEMOGRAPH_AUTH_PROVIDER=none, require_user returns an anonymous
    # user rather than 401-ing — preserves local-dev workflows.
    from .routes import admin, ai, analytics, graph, memories, search

    auth_dep = [Depends(require_user)]
    # Admin router is gated by an additional `admin` scope. The scope
    # claim is supplied by the auth provider (custom claim on the JWT or
    # a dedicated API key with the scope encoded). require_scope first
    # invokes require_user, so unauthenticated callers see 401, not 403.
    admin_dep = [Depends(require_scope("admin"))]
    for prefix in ("/api/v1", "/api"):
        app.include_router(
            memories.router, prefix=prefix, tags=["memories"], dependencies=auth_dep
        )
        app.include_router(
            search.router, prefix=prefix, tags=["search"], dependencies=auth_dep
        )
        app.include_router(
            graph.router, prefix=prefix, tags=["graph"], dependencies=auth_dep
        )
        app.include_router(
            analytics.router, prefix=prefix, tags=["analytics"], dependencies=auth_dep
        )
        app.include_router(ai.router, prefix=prefix, tags=["ai"], dependencies=auth_dep)
        app.include_router(admin.router, prefix=prefix, dependencies=admin_dep)

    if _METRICS_ENABLED:

        @app.get("/metrics", include_in_schema=False)
        async def metrics():
            """Prometheus exposition. Enabled by MEMOGRAPH_METRICS_ENABLED=1.

            Intentionally not gated by auth — most Prometheus scrapers can't
            send headers; protect this with a network-level allowlist (only
            reachable from the metrics-collector pod/host) instead.
            """
            return metrics_endpoint()

    # Wire OpenTelemetry exporter if configured. No-op when env vars aren't
    # set, so the [observability] extra is genuinely optional.
    init_telemetry(app)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness probe.

        Returns 200 as long as the process is up. Does not touch the
        kernel, the vault, or any I/O — orchestrators should restart the
        pod only when this endpoint is unreachable, not when the kernel
        is slow.
        """
        return {"status": "alive"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz(request: Request) -> JSONResponse:
        """Readiness probe.

        Returns 200 only after the startup ingest has succeeded; 503
        otherwise. Orchestrators should withhold traffic until this is
        green so requests don't race kernel initialization.
        """
        is_ready = bool(getattr(request.app.state, "is_ready", False))
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content={"status": "ready" if is_ready else "not_ready"},
        )

    @app.get("/api/v1/auth/me")
    async def whoami(user=Depends(require_user)):
        """Introspection: return the caller's identity without leaking
        raw claims. Useful for clients that need to know which scopes
        they have."""
        return {
            "id": user.id,
            "email": user.email,
            "organization_id": user.organization_id,
            "scopes": list(user.scopes),
        }

    @app.get("/api/v1/health")
    @app.get("/api/health")
    async def health(request: Request):
        """Public health check.

        Intentionally minimal. Internal diagnostic fields (vault path,
        memory/entity counts, feature flags) are gated behind
        MEMOGRAPH_DEBUG=1 so they don't leak when the endpoint is
        exposed publicly. Prefer /healthz (liveness) and /readyz
        (readiness) for orchestration probes — those are stable.
        """
        body: dict[str, object] = {
            "status": "healthy",
            "timestamp": time.time(),
        }
        if _DEBUG_ENABLED:
            registry = getattr(request.app.state, "tenant_registry", None)
            body["version"] = "1.0.0"
            body["gam_enabled"] = request.app.state.use_gam
            if registry is not None:
                # Multi-tenant: report tenant cardinality, not per-tenant
                # vault contents. The admin API serves per-tenant detail.
                body["multi_tenant"] = True
                body["warm_tenants"] = len(registry.warm_tenants())
                body["known_tenants"] = len(registry.known_tenants())
            else:
                kernel = getattr(request.app.state, "kernel", None)
                body["vault_path"] = request.app.state.vault_path
                if kernel is not None:
                    body["total_memories"] = len(kernel.graph.all_nodes())
                    body["total_entities"] = len(kernel.graph.all_entities())
        return body

    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "name": "MemoGraph API",
            "version": "1.0.0",
            "docs": "/api/docs",
            "health": "/healthz",
            "readiness": "/readyz",
        }

    logger.info("MemoGraph server initialized successfully")

    return app


def run_dev_server(
    vault_path: str, host: str = "0.0.0.0", port: int = 8000, use_gam: bool = True
):
    """Run the development server."""
    import uvicorn

    app = create_app(vault_path, use_gam)

    logger.info(f"Starting development server on {host}:{port}")
    logger.info(f"API docs available at: http://{host}:{port}/api/docs")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=False,  # Set to True for auto-reload during development
    )


if __name__ == "__main__":
    import sys

    vault_path = sys.argv[1] if len(sys.argv) > 1 else "./vault"
    run_dev_server(vault_path)
