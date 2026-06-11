"""FastAPI server for MemoGraph web UI."""

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from ...core.kernel import MemoryKernel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# When MEMOGRAPH_DEBUG=1, the 500 handler echoes the exception string and
# /api/health returns the vault path. In production this leaks internals
# to clients; default off, opt-in for local debugging only.
_DEBUG_ENABLED = os.environ.get("MEMOGRAPH_DEBUG", "").lower() in {"1", "true", "yes"}


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    logger.info("Starting MemoGraph server...")
    # Startup: ingest vault if not already done
    try:
        if app.state.kernel:
            logger.info("Ingesting vault on startup...")
            stats = await app.state.kernel.ingest_async(force=False)
            logger.info(f"Vault ingested: {stats['total']} memories loaded")
    except Exception as e:
        logger.error(f"Failed to ingest vault on startup: {e}")

    yield

    # Shutdown
    logger.info("Shutting down MemoGraph server...")


def create_app(vault_path: str, use_gam: bool = True) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        vault_path: Path to the vault directory
        use_gam: Whether to enable Graph Attention Memory (GAM)

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="MemoGraph API",
        version="1.0.0",
        description="Production-ready API for MemoGraph memory management system",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS middleware - configure for production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:5173",  # Vite dev server
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Gzip compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Initialize kernel
    vault_path_obj = Path(vault_path).expanduser()
    logger.info(f"Initializing kernel with vault: {vault_path_obj}")

    kernel = MemoryKernel(vault_path=str(vault_path_obj), use_gam=use_gam)

    app.state.kernel = kernel
    app.state.vault_path = str(vault_path_obj)
    app.state.use_gam = use_gam

    # Error handler
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "code": f"HTTP_{exc.status_code}",
                "path": str(request.url),
            },
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

    # Request timing middleware
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response

    # Import and register routes
    from .routes import ai, analytics, graph, memories, search

    app.include_router(memories.router, prefix="/api", tags=["memories"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.include_router(graph.router, prefix="/api", tags=["graph"])
    app.include_router(analytics.router, prefix="/api", tags=["analytics"])
    app.include_router(ai.router, prefix="/api", tags=["ai"])

    # Health check endpoint
    @app.get("/api/health")
    async def health(request: Request):
        """Public health check.

        Intentionally minimal. Internal diagnostic fields (vault path,
        memory/entity counts, feature flags) are gated behind
        MEMOGRAPH_DEBUG=1 so they don't leak when the endpoint is
        exposed publicly. Use /healthz / /readyz once Phase 1 lands
        the dedicated probes.
        """
        body: dict[str, object] = {
            "status": "healthy",
            "timestamp": time.time(),
        }
        if _DEBUG_ENABLED:
            kernel = request.app.state.kernel
            body.update(
                {
                    "version": "1.0.0",
                    "vault_path": request.app.state.vault_path,
                    "total_memories": len(kernel.graph.all_nodes()),
                    "total_entities": len(kernel.graph.all_entities()),
                    "gam_enabled": request.app.state.use_gam,
                }
            )
        return body

    # Root endpoint
    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "name": "MemoGraph API",
            "version": "1.0.0",
            "docs": "/api/docs",
            "health": "/api/health",
        }

    logger.info("MemoGraph server initialized successfully")

    return app


def run_dev_server(
    vault_path: str, host: str = "0.0.0.0", port: int = 8000, use_gam: bool = True
):
    """
    Run the development server.

    Args:
        vault_path: Path to the vault directory
        host: Host to bind to
        port: Port to bind to
        use_gam: Whether to enable GAM
    """
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
