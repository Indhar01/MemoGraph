"""Lifespan wiring tests for the source-adapter sync scheduler.

These exercise the FastAPI startup hook: when ``MEMOGRAPH_SOURCES_ENABLED``
is not explicitly disabled (default-on as of v1.1) and the sync knob is
off, the app should construct a :class:`SyncScheduler`, attach it to
``app.state.sync_scheduler``, and stop it cleanly on shutdown.

We use :class:`fastapi.testclient.TestClient` as a context manager so
the lifespan handlers actually run (the bare-instance form skips
them).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


def _reload_server(monkeypatch: pytest.MonkeyPatch, sources_root: Path, **env: str):
    """Reload the server module with a fresh env snapshot."""
    monkeypatch.delenv("MEMOGRAPH_DEBUG", raising=False)
    monkeypatch.delenv("MEMOGRAPH_TENANCY_ENABLED", raising=False)
    monkeypatch.setenv("MEMOGRAPH_SOURCES_ROOT", str(sources_root))
    # Default to api_key auth with no keys — lifespan doesn't need
    # a caller; route tests use a different fixture.
    monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "none")
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    from memograph.web.backend import auth as auth_mod
    from memograph.web.backend import server as server_mod

    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    auth_mod._reset_oidc_state()
    return server_mod


@pytest.fixture
def sources_root(tmp_path: Path) -> Path:
    p = tmp_path / "sources-root"
    p.mkdir()
    return p


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    p = tmp_path / "vault"
    p.mkdir()
    return p


def test_scheduler_started_when_sources_enabled(
    monkeypatch: pytest.MonkeyPatch,
    sources_root: Path,
    vault_dir: Path,
) -> None:
    server_mod = _reload_server(
        monkeypatch,
        sources_root,
        MEMOGRAPH_SOURCES_ENABLED="1",
    )
    app = server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
    with TestClient(app):
        scheduler = app.state.sync_scheduler
        assert scheduler is not None
        # The asyncio task is created on start() and is still alive.
        assert scheduler._task is not None
        assert not scheduler._task.done()
    # After the context manager exits, the scheduler has been stopped.
    assert app.state.sync_scheduler is not None  # reference preserved
    assert (
        app.state.sync_scheduler._task is None
        or app.state.sync_scheduler._task.done()
    )


def test_scheduler_skipped_when_sources_disabled(
    monkeypatch: pytest.MonkeyPatch,
    sources_root: Path,
    vault_dir: Path,
) -> None:
    # MEMOGRAPH_SOURCES_ENABLED=0 — operator opted out; registry stays
    # None and the scheduler should never be constructed.
    monkeypatch.setenv("MEMOGRAPH_SOURCES_ENABLED", "0")
    server_mod = _reload_server(monkeypatch, sources_root)
    app = server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
    with TestClient(app):
        assert app.state.source_registry is None
        assert app.state.sync_scheduler is None


def test_scheduler_skipped_when_sync_disabled(
    monkeypatch: pytest.MonkeyPatch,
    sources_root: Path,
    vault_dir: Path,
) -> None:
    # Operator wants the routes available but no automatic sync —
    # registry yes, scheduler no.
    server_mod = _reload_server(
        monkeypatch,
        sources_root,
        MEMOGRAPH_SOURCES_ENABLED="1",
        MEMOGRAPH_SOURCES_SYNC_DISABLED="1",
    )
    app = server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
    with TestClient(app):
        assert app.state.source_registry is not None
        assert app.state.sync_scheduler is None
