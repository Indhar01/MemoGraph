"""End-to-end tests for the /api/v1/sources router.

These tests exercise the assembled app through ``TestClient`` so we
catch wiring regressions (router not mounted under both prefixes,
auth dependency missing, registry not initialized at startup) along
with the route bodies themselves.

Auth pattern matches ``tests/tenancy/test_admin_routes.py``: the
api_key provider is wired, two test keys are minted, and the
verifier is monkeypatched so ``admin-key`` carries the ``admin``
scope while ``user-key`` does not. This is the lightest-weight way
to exercise both the read paths (open to any authenticated user)
and the mutating paths (admin-only) without standing up an OIDC
authorisation server in tests.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


ADMIN_HEADER = {"X-API-Key": "admin-key"}
USER_HEADER = {"X-API-Key": "user-key"}


@pytest.fixture
def sources_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point SourceRegistry at an isolated dir so tests don't trash
    the user's real configs."""
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
    """Reload the server module with MEMOGRAPH_SOURCES_ENABLED=1 and
    api_key auth wired with an admin-scoped key.

    The verifier is monkeypatched so:
      * ``X-API-Key: admin-key`` → user with scopes (api_key, admin)
      * ``X-API-Key: user-key`` → user with scopes (api_key,)
    """
    monkeypatch.delenv("MEMOGRAPH_DEBUG", raising=False)
    monkeypatch.delenv("MEMOGRAPH_LOG_JSON", raising=False)
    monkeypatch.delenv("MEMOGRAPH_TENANCY_ENABLED", raising=False)
    monkeypatch.delenv("MEMOGRAPH_READONLY", raising=False)
    monkeypatch.setenv("MEMOGRAPH_SOURCES_ENABLED", "1")
    monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
    monkeypatch.setenv("MEMOGRAPH_API_KEYS", "admin-key,user-key")

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
        if key == "admin-key":
            return auth_mod.User(
                id=user.id,
                email=user.email,
                organization_id=user.organization_id,
                scopes=("api_key", "admin"),
                raw_claims=user.raw_claims,
            )
        return user

    monkeypatch.setattr(auth_mod, "_verify_api_key", _verify_with_scopes)
    return server_mod


@pytest.fixture
def disabled_server(monkeypatch: pytest.MonkeyPatch):
    """Reload the server module with the sources opt-out flag set."""
    monkeypatch.delenv("MEMOGRAPH_DEBUG", raising=False)
    monkeypatch.delenv("MEMOGRAPH_LOG_JSON", raising=False)
    monkeypatch.setenv("MEMOGRAPH_SOURCES_ENABLED", "0")

    from memograph.web.backend import server as server_mod

    return importlib.reload(server_mod)


def _client(server_module, vault_dir: Path) -> TestClient:
    app = server_module.create_app(vault_path=str(vault_dir), use_gam=False)
    app.state.kernel.ingest()
    app.state.is_ready = True
    return TestClient(app)


def _create_local(client: TestClient, source_id: str, path: Path, *, headers=None):
    return client.post(
        "/api/v1/sources",
        json={
            "source_id": source_id,
            "kind": "local",
            "display_name": source_id.replace("-", " ").title(),
            "params": {"path": str(path)},
        },
        headers=headers if headers is not None else ADMIN_HEADER,
    )


class TestFeatureFlag:
    def test_disabled_returns_404_on_list(
        self, disabled_server, vault_dir: Path
    ) -> None:
        # When operator opts out (MEMOGRAPH_SOURCES_ENABLED=0), the
        # router is not mounted — 404, not 503.
        client = _client(disabled_server, vault_dir)
        r = client.get("/api/v1/sources")
        assert r.status_code == 404

    def test_enabled_lists_empty(self, sources_server, vault_dir: Path) -> None:
        client = _client(sources_server, vault_dir)
        r = client.get("/api/v1/sources", headers=USER_HEADER)
        assert r.status_code == 200
        body = r.json()
        assert body == {"sources": [], "active_source_id": None, "total": 0}


class TestAuthorization:
    def test_unauthenticated_list_is_401(self, sources_server, vault_dir: Path) -> None:
        client = _client(sources_server, vault_dir)
        r = client.get("/api/v1/sources")
        assert r.status_code == 401

    def test_non_admin_can_read(
        self, sources_server, vault_dir: Path, tmp_path: Path
    ) -> None:
        # Seed a source as admin.
        client = _client(sources_server, vault_dir)
        target = tmp_path / "v"
        target.mkdir()
        _create_local(client, "primary", target)
        # User scope can read.
        r = client.get("/api/v1/sources", headers=USER_HEADER)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_non_admin_cannot_create(
        self, sources_server, vault_dir: Path, tmp_path: Path
    ) -> None:
        client = _client(sources_server, vault_dir)
        target = tmp_path / "v"
        target.mkdir()
        r = _create_local(client, "primary", target, headers=USER_HEADER)
        assert r.status_code == 403

    def test_non_admin_cannot_delete(
        self, sources_server, vault_dir: Path, tmp_path: Path
    ) -> None:
        client = _client(sources_server, vault_dir)
        target = tmp_path / "v"
        target.mkdir()
        _create_local(client, "primary", target)
        r = client.delete("/api/v1/sources/primary", headers=USER_HEADER)
        assert r.status_code == 403


class TestCreateSource:
    def test_create_local(
        self,
        sources_server,
        sources_root: Path,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "local-vault-1"
        target.mkdir()
        client = _client(sources_server, vault_dir)
        r = _create_local(client, "primary", target)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["source_id"] == "primary"
        assert body["kind"] == "local"
        # First-source auto-activate: with no prior active source,
        # the new one is immediately activated so the kernel re-points
        # at it and the user doesn't have to click Activate manually.
        assert body["is_active"] is True
        assert (sources_root / ".sources" / "primary.json").exists()

    def test_create_onedrive_redirects_to_connect_flow(
        self, sources_server, vault_dir: Path
    ) -> None:
        # OneDrive sources go through Nango Connect. The direct POST
        # route refuses them with a 400 pointing at /connect-session.
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "od-personal",
                "kind": "onedrive",
                "display_name": "OneDrive",
                "params": {},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 400
        assert "connect-session" in r.json()["error"]

    def test_create_gdrive_redirects_to_connect_flow(
        self, sources_server, vault_dir: Path
    ) -> None:
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "gdrive-personal",
                "kind": "gdrive",
                "display_name": "Drive",
                "params": {},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 400
        assert "connect-session" in r.json()["error"]

    def test_create_s3_source(
        self, sources_server, vault_dir: Path, sources_root: Path
    ) -> None:
        # The S3 adapter is an out-of-tree plugin capability (moved to
        # memograph-enterprise). Register a lightweight stub adapter into the
        # public adapter registry so this test verifies the route + registry
        # contract independently of whether the S3 plugin is installed.
        from memograph.sources import adapter_registry
        from memograph.sources.base import Source, SourceKind

        class _StubS3(Source):
            async def list_documents(self):  # pragma: no cover
                if False:
                    yield None

            async def read_document(self, doc_id):  # pragma: no cover
                raise NotImplementedError

            async def write_document(self, doc):  # pragma: no cover
                raise NotImplementedError

            async def watch(self):  # pragma: no cover
                if False:
                    yield None

            async def materialize_to_vault(self, vault_path):  # pragma: no cover
                raise NotImplementedError

            async def health(self):  # pragma: no cover
                raise NotImplementedError

        adapter_registry.register_source_adapter(
            SourceKind.S3, _StubS3, override=True
        )
        try:
            client = _client(sources_server, vault_dir)
            r = client.post(
                "/api/v1/sources",
                json={
                    "source_id": "s3-primary",
                    "kind": "s3",
                    "display_name": "Primary S3",
                    "params": {
                        "bucket": "my-bucket",
                        "prefix": "memos",
                        "region": "us-east-1",
                    },
                },
                headers=ADMIN_HEADER,
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["kind"] == "s3"
            # Only recognised fields persist - typos are dropped.
            persisted = (sources_root / ".sources" / "s3-primary.json").read_text(
                encoding="utf-8"
            )
            assert "my-bucket" in persisted
            assert "us-east-1" in persisted
        finally:
            adapter_registry._reset_for_tests()

    def test_create_s3_requires_bucket(self, sources_server, vault_dir: Path) -> None:
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "s3-empty",
                "kind": "s3",
                "display_name": "Empty",
                "params": {},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 400
        assert "bucket" in r.json()["error"].lower()

    def test_create_notion_source_with_connection_id(
        self, sources_server, vault_dir: Path
    ) -> None:
        # Scripted creation: caller pre-minted a Nango connection
        # and supplies its id. Route accepts the source structurally;
        # the adapter will refuse at first call if the connection
        # is missing on the Nango side, but that's the right place
        # to discover it.
        #
        # NOTION sources can't be materialised without a NangoClient,
        # so we inject a stub onto the app state so registry.register()
        # (which warms the source) doesn't trip the misconfig guard.
        app = sources_server.create_app(vault_path=str(vault_dir), use_gam=False)
        app.state.kernel.ingest()
        app.state.is_ready = True

        class _StubNango:
            pass

        app.state.nango_client = _StubNango()
        app.state.source_registry._nango_client = app.state.nango_client
        from fastapi.testclient import TestClient

        client = TestClient(app)
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "notion-team",
                "kind": "notion",
                "display_name": "Team Wiki",
                "params": {
                    "nango_connection_id": "conn-test-1",
                    "database_id": "abcdef",
                },
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["kind"] == "notion"
        assert body["params"]["nango_connection_id"] == "conn-test-1"
        assert body["params"]["database_id"] == "abcdef"

    def test_create_notion_requires_nango_connection_id(
        self,
        sources_server,
        vault_dir: Path,
    ) -> None:
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "notion-empty",
                "kind": "notion",
                "display_name": "Empty",
                "params": {},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 400
        assert "nango_connection_id" in r.json()["error"]

    def test_create_rejects_relative_path(
        self, sources_server, vault_dir: Path
    ) -> None:
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "primary",
                "kind": "local",
                "display_name": "Primary",
                "params": {"path": "relative/path"},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 400
        assert "absolute" in r.json()["error"]

    def test_create_rejects_nonexistent_local_path(
        self, sources_server, vault_dir: Path, tmp_path: Path
    ) -> None:
        # Wizard ergonomics: the user must learn at create time that
        # the path doesn't exist, not after the health probe.
        missing = tmp_path / "definitely-not-here"
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "primary",
                "kind": "local",
                "display_name": "Primary",
                "params": {"path": str(missing)},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 400
        body = r.json()
        assert "does not exist" in body["error"]
        # The resolved path the backend saw is echoed in the error so
        # the user can spot OS-level mangling.
        assert "definitely-not-here" in body["error"]

    def test_create_rejects_file_as_local_path(
        self, sources_server, vault_dir: Path, tmp_path: Path
    ) -> None:
        # Pointing at a file (rather than a directory) is a common
        # wizard slip — surface it as a clean 400 with a hint.
        f = tmp_path / "notes.md"
        f.write_text("# hi", encoding="utf-8")
        client = _client(sources_server, vault_dir)
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "primary",
                "kind": "local",
                "display_name": "Primary",
                "params": {"path": str(f)},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 400
        assert "not a directory" in r.json()["error"]

    def test_create_local_trims_quotes_and_whitespace(
        self, sources_server, vault_dir: Path, tmp_path: Path
    ) -> None:
        # Copy-pasting from a terminal often wraps paths in quotes;
        # wizard should be forgiving about that.
        target = tmp_path / "quoted"
        target.mkdir()
        client = _client(sources_server, vault_dir)
        wrapped = f'  "{target}"  '
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "primary",
                "kind": "local",
                "display_name": "Primary",
                "params": {"path": wrapped},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 201, r.text

    def test_create_rejects_path_traversal(
        self, sources_server, vault_dir: Path, tmp_path: Path
    ) -> None:
        client = _client(sources_server, vault_dir)
        # Build a path that's absolute on both POSIX and Windows but
        # contains a literal ".." segment. ``tmp_path`` is always
        # absolute; appending ``..`` gives us the traversal we want.
        traversal_path = str(tmp_path / "outside" / ".." / "escape")
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "primary",
                "kind": "local",
                "display_name": "Primary",
                "params": {"path": traversal_path},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 400
        assert "'..'" in r.json()["error"]


class TestActivate:
    def test_activate_writes_marker_and_audits(
        self,
        sources_server,
        sources_root: Path,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "v"
        target.mkdir()
        client = _client(sources_server, vault_dir)
        _create_local(client, "primary", target)
        r = client.post("/api/v1/sources/primary/activate", headers=ADMIN_HEADER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["active_source_id"] == "primary"
        # Create auto-activates the first source, so a subsequent
        # explicit Activate of the same source reports itself as the
        # previous active — idempotent under repeated clicks.
        assert body["previous_active_source_id"] == "primary"
        active = client.get("/api/v1/sources/active", headers=USER_HEADER)
        assert active.status_code == 200
        assert active.json()["source_id"] == "primary"
        # Audit log captured create + activate.
        log_path = sources_root / ".sources" / "_audit.log"
        assert log_path.exists()
        lines = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        actions = [entry["action"] for entry in lines]
        assert "source.create" in actions
        assert "source.activate" in actions

    def test_activate_unknown_source_404s(
        self, sources_server, vault_dir: Path
    ) -> None:
        client = _client(sources_server, vault_dir)
        r = client.post("/api/v1/sources/never-existed/activate", headers=ADMIN_HEADER)
        assert r.status_code == 404


class TestManualSync:
    def test_sync_runs_immediately_for_local(
        self,
        sources_server,
        sources_root: Path,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "v"
        target.mkdir()
        (target / "a.md").write_text("# A", encoding="utf-8")
        client = _client(sources_server, vault_dir)
        _create_local(client, "primary", target)
        r = client.post("/api/v1/sources/primary/sync", headers=ADMIN_HEADER)
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["source_id"] == "primary"
        assert body["in_flight"] is False
        assert body["last_success_at"] is not None
        assert body["last_error"] is None
        # Audit log got the sync entry.
        log_path = sources_root / ".sources" / "_audit.log"
        lines = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(e["action"] == "source.sync" for e in lines)

    def test_sync_unknown_source_404s(self, sources_server, vault_dir: Path) -> None:
        client = _client(sources_server, vault_dir)
        r = client.post("/api/v1/sources/never-existed/sync", headers=ADMIN_HEADER)
        assert r.status_code == 404

    def test_sync_requires_admin(
        self,
        sources_server,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "v"
        target.mkdir()
        client = _client(sources_server, vault_dir)
        _create_local(client, "primary", target)
        r = client.post("/api/v1/sources/primary/sync", headers=USER_HEADER)
        assert r.status_code == 403


class TestGet:
    def test_get_returns_existing(
        self,
        sources_server,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "v"
        target.mkdir()
        client = _client(sources_server, vault_dir)
        _create_local(client, "primary", target)
        r = client.get("/api/v1/sources/primary", headers=USER_HEADER)
        assert r.status_code == 200
        assert r.json()["source_id"] == "primary"

    def test_get_unknown_404s(self, sources_server, vault_dir: Path) -> None:
        client = _client(sources_server, vault_dir)
        r = client.get("/api/v1/sources/never-existed", headers=USER_HEADER)
        assert r.status_code == 404

    def test_get_active_404s_when_none_set(
        self, sources_server, vault_dir: Path
    ) -> None:
        client = _client(sources_server, vault_dir)
        r = client.get("/api/v1/sources/active", headers=USER_HEADER)
        assert r.status_code == 404


class TestHealth:
    def test_health_returns_ok_for_local(
        self,
        sources_server,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "v"
        target.mkdir()
        (target / "alpha.md").write_text("# Alpha", encoding="utf-8")
        client = _client(sources_server, vault_dir)
        _create_local(client, "primary", target)
        r = client.get("/api/v1/sources/primary/health", headers=USER_HEADER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["documents_total"] == 1


class TestDelete:
    def test_delete_is_204(
        self,
        sources_server,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "v"
        target.mkdir()
        client = _client(sources_server, vault_dir)
        _create_local(client, "primary", target)
        r = client.delete("/api/v1/sources/primary", headers=ADMIN_HEADER)
        assert r.status_code == 204
        # Second delete is idempotent.
        r2 = client.delete("/api/v1/sources/primary", headers=ADMIN_HEADER)
        assert r2.status_code == 204
        # GET now 404s.
        assert (
            client.get("/api/v1/sources/primary", headers=USER_HEADER).status_code
            == 404
        )


class TestReadOnlyModeBlocks:
    """The ReadOnlyMiddleware must reject source mutations when
    MEMOGRAPH_READONLY=true is set."""

    def test_create_blocked_in_readonly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sources_root: Path,
        vault_dir: Path,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("MEMOGRAPH_READONLY", "true")
        monkeypatch.setenv("MEMOGRAPH_SOURCES_ENABLED", "1")
        monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
        monkeypatch.setenv("MEMOGRAPH_API_KEYS", "admin-key")
        from memograph.web.backend import auth as auth_mod
        from memograph.web.backend import middleware as middleware_mod
        from memograph.web.backend import server as server_mod

        importlib.reload(auth_mod)
        importlib.reload(middleware_mod)
        importlib.reload(server_mod)
        auth_mod._reset_oidc_state()

        original = auth_mod._verify_api_key

        def _admin_user(key: str):
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

        monkeypatch.setattr(auth_mod, "_verify_api_key", _admin_user)

        target = tmp_path / "v"
        target.mkdir()
        client = _client(server_mod, vault_dir)
        r = client.post(
            "/api/v1/sources",
            json={
                "source_id": "primary",
                "kind": "local",
                "display_name": "Primary",
                "params": {"path": str(target)},
            },
            headers=ADMIN_HEADER,
        )
        assert r.status_code == 403
        assert r.json()["code"] == "READ_ONLY_MODE"

    def test_get_still_works_in_readonly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sources_root: Path,
        vault_dir: Path,
    ) -> None:
        monkeypatch.setenv("MEMOGRAPH_READONLY", "true")
        monkeypatch.setenv("MEMOGRAPH_SOURCES_ENABLED", "1")
        monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
        monkeypatch.setenv("MEMOGRAPH_API_KEYS", "admin-key")
        from memograph.web.backend import auth as auth_mod
        from memograph.web.backend import middleware as middleware_mod
        from memograph.web.backend import server as server_mod

        importlib.reload(auth_mod)
        importlib.reload(middleware_mod)
        importlib.reload(server_mod)
        auth_mod._reset_oidc_state()

        client = _client(server_mod, vault_dir)
        r = client.get("/api/v1/sources", headers=ADMIN_HEADER)
        assert r.status_code == 200
