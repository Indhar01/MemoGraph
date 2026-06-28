"""End-to-end tests for the kernel-binding glue.

These exercise the wire from "user adds a Local source" → "kernel
re-points at that folder and indexes the .md files" — the link that
was missing in the previous build and made Sources page green +
Memories page empty.

Fixtures mirror ``tests/web/test_sources_routes.py`` (which is not a
Python package, so we can't import from it). Duplication is
deliberate: kernel-binding tests need to assert post-lifespan state
the routes tests don't touch, so the test bodies diverge anyway.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


ADMIN_HEADER = {"X-API-Key": "admin-key"}


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
def sources_server(
    monkeypatch: pytest.MonkeyPatch,
    sources_root: Path,
):
    monkeypatch.delenv("MEMOGRAPH_DEBUG", raising=False)
    monkeypatch.delenv("MEMOGRAPH_LOG_JSON", raising=False)
    monkeypatch.delenv("MEMOGRAPH_TENANCY_ENABLED", raising=False)
    monkeypatch.delenv("MEMOGRAPH_READONLY", raising=False)
    monkeypatch.setenv("MEMOGRAPH_SOURCES_ENABLED", "1")
    monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
    monkeypatch.setenv("MEMOGRAPH_API_KEYS", "admin-key")

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
        return auth_mod.User(
            id=user.id,
            email=user.email,
            organization_id=user.organization_id,
            scopes=("api_key", "admin"),
            raw_claims=user.raw_claims,
        )

    monkeypatch.setattr(auth_mod, "_verify_api_key", _verify_with_scopes)
    return server_mod


def _create_local(client: TestClient, source_id: str, path: Path):
    return client.post(
        "/api/v1/sources",
        json={
            "source_id": source_id,
            "kind": "local",
            "display_name": source_id,
            "params": {"path": str(path)},
        },
        headers=ADMIN_HEADER,
    )


def _seed_markdown(folder: Path, names: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / f"{n}.md").write_text(
            f"# {n}\n\nlinks to [[{names[0]}]]\n",
            encoding="utf-8",
        )


async def _poll_for_nodes(app, expected: int, timeout: float = 5.0) -> int:
    """Await until kernel.graph has ``expected`` nodes (or timeout)."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        kernel = getattr(app.state, "kernel", None)
        if kernel is not None:
            nodes = len(kernel.graph.all_nodes())
            if nodes >= expected:
                return nodes
        await asyncio.sleep(0.05)
    kernel = getattr(app.state, "kernel", None)
    return len(kernel.graph.all_nodes()) if kernel else 0


class TestFirstSourceAutoActivate:
    @pytest.mark.asyncio
    async def test_local_source_indexes_into_kernel(
        self,
        sources_server,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Creating a Local source as the first source should:

        * auto-activate it (is_active=True in the create response)
        * swap app.state.kernel to point at the source's folder
        * trigger a background ingest that materializes the .md files
          into the graph
        """
        target = tmp_path / "notes"
        _seed_markdown(target, ["alpha", "beta", "gamma"])
        app = sources_server.create_app(vault_path=str(vault_dir), use_gam=False)
        with TestClient(app) as client:
            r = _create_local(client, "primary", target)
            assert r.status_code == 201, r.text
            assert r.json()["is_active"] is True
            assert (
                Path(app.state.vault_path).resolve() == target.resolve()
            ), f"kernel still on {app.state.vault_path}"
            nodes = await _poll_for_nodes(app, expected=3, timeout=5.0)
            assert nodes >= 3, f"expected ≥3 nodes after ingest, got {nodes}"


class TestActivateSwapsKernel:
    @pytest.mark.asyncio
    async def test_activate_second_source_re_points_kernel(
        self,
        sources_server,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Activating a different source should re-point the kernel
        AND trigger a fresh ingest of the new folder."""
        first = tmp_path / "first"
        second = tmp_path / "second"
        _seed_markdown(first, ["one", "two"])
        _seed_markdown(second, ["alpha", "beta", "gamma", "delta"])

        app = sources_server.create_app(vault_path=str(vault_dir), use_gam=False)
        with TestClient(app) as client:
            _create_local(client, "first", first)
            await _poll_for_nodes(app, expected=2, timeout=5.0)
            assert Path(app.state.vault_path).resolve() == first.resolve()

            r2 = _create_local(client, "second", second)
            assert r2.status_code == 201
            assert r2.json()["is_active"] is False
            assert Path(app.state.vault_path).resolve() == first.resolve()

            r3 = client.post("/api/v1/sources/second/activate", headers=ADMIN_HEADER)
            assert r3.status_code == 200, r3.text
            assert Path(app.state.vault_path).resolve() == second.resolve()
            nodes = await _poll_for_nodes(app, expected=4, timeout=5.0)
            assert nodes >= 4, f"expected ≥4 nodes after activate swap, got {nodes}"
