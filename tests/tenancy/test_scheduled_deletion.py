"""End-to-end tests for the scheduled-deletion runbook (Phase 3.7).

Covers three layers:

1. Admin route: schedule, status, cancel.
2. tenant_resolver: tombstoned tenant returns 410 to non-admin
   callers but admin routes still work.
3. Reaper: expired tombstones get destroyed; non-expired don't;
   final backups are written; corrupted tombstones reported but
   not silently destroyed.
"""

from __future__ import annotations

import importlib
import json
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memograph.storage.tombstone import (
    TOMBSTONE_FILENAME,
    is_tombstoned,
    tombstone_path,
    write_tombstone,
)

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def global_root(tmp_path: Path) -> Path:
    d = tmp_path / "tenants"
    d.mkdir()
    return d


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture
def server_mod(monkeypatch, global_root):
    monkeypatch.setenv("MEMOGRAPH_TENANCY_ENABLED", "1")
    monkeypatch.setenv("MEMOGRAPH_GLOBAL_ROOT", str(global_root))
    monkeypatch.setenv("MEMOGRAPH_AUTH_PROVIDER", "api_key")
    monkeypatch.setenv("MEMOGRAPH_API_KEYS", "key-acme,key-admin")

    from memograph.web.backend import auth as auth_mod
    from memograph.web.backend import server as server_mod

    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    auth_mod._reset_oidc_state()

    original = auth_mod._verify_api_key
    bindings = {
        "key-acme": ("acme", ("api_key",)),
        "key-admin": ("acme", ("api_key", "admin")),
    }

    def _verify(key: str):
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

    monkeypatch.setattr(auth_mod, "_verify_api_key", _verify)
    return server_mod


@pytest.fixture
def client(server_mod, vault_dir):
    app = server_mod.create_app(vault_path=str(vault_dir), use_gam=False)
    app.state.is_ready = True
    return TestClient(app)


def _hdr(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def _create_memory(client, key: str, title: str = "Note", content: str = "x"):
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


# ---------------------------------------------------- admin route surface


def test_schedule_delete_writes_tombstone(client, global_root):
    _create_memory(client, "key-acme")
    r = client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 3, "reason": "GDPR request #42"},
        headers=_hdr("key-admin"),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["reason"] == "GDPR request #42"
    assert is_tombstoned(global_root / "acme")


def test_schedule_delete_404_for_unknown(client):
    r = client.post(
        "/api/v1/admin/tenants/nope/schedule-delete",
        json={"grace_days": 1},
        headers=_hdr("key-admin"),
    )
    assert r.status_code == 404


def test_double_schedule_returns_409(client):
    _create_memory(client, "key-acme")
    client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 1},
        headers=_hdr("key-admin"),
    )
    r = client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 1},
        headers=_hdr("key-admin"),
    )
    assert r.status_code == 409


def test_cancel_clears_tombstone(client, global_root):
    _create_memory(client, "key-acme")
    client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 7},
        headers=_hdr("key-admin"),
    )
    assert is_tombstoned(global_root / "acme")
    r = client.delete(
        "/api/v1/admin/tenants/acme/schedule-delete",
        headers=_hdr("key-admin"),
    )
    assert r.status_code == 204
    assert not is_tombstoned(global_root / "acme")


def test_cancel_404_when_no_tombstone(client):
    _create_memory(client, "key-acme")
    r = client.delete(
        "/api/v1/admin/tenants/acme/schedule-delete",
        headers=_hdr("key-admin"),
    )
    assert r.status_code == 404


def test_get_tenant_reports_tombstone(client):
    _create_memory(client, "key-acme")
    client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 5},
        headers=_hdr("key-admin"),
    )
    r = client.get("/api/v1/admin/tenants/acme", headers=_hdr("key-admin"))
    assert r.status_code == 200
    body = r.json()
    assert body["tombstoned"] is True
    assert body["tombstone_scheduled_at"] is not None
    assert body["tombstone_delete_after"] is not None


def test_list_tenants_reports_tombstone(client):
    _create_memory(client, "key-acme")
    client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 2},
        headers=_hdr("key-admin"),
    )
    r = client.get("/api/v1/admin/tenants", headers=_hdr("key-admin"))
    assert r.status_code == 200
    [item] = r.json()["tenants"]
    assert item["tombstoned"] is True


def test_create_tenant_refused_while_tombstoned(client):
    _create_memory(client, "key-acme")
    client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 7},
        headers=_hdr("key-admin"),
    )
    r = client.post(
        "/api/v1/admin/tenants",
        json={"tenant_id": "acme"},
        headers=_hdr("key-admin"),
    )
    assert r.status_code == 409


# -------------------------------------------------- routing layer (410 Gone)


def test_non_admin_request_returns_410_when_tombstoned(client):
    _create_memory(client, "key-acme")
    client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 3},
        headers=_hdr("key-admin"),
    )
    r = client.get("/api/v1/memories", headers=_hdr("key-acme"))
    assert r.status_code == 410


def test_admin_routes_still_work_when_tombstoned(client):
    _create_memory(client, "key-acme")
    client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 3},
        headers=_hdr("key-admin"),
    )
    # Status check is the canonical use case: operator wants to see
    # the tombstone exists.
    r = client.get("/api/v1/admin/tenants/acme", headers=_hdr("key-admin"))
    assert r.status_code == 200


def test_410_clears_after_cancel(client):
    _create_memory(client, "key-acme")
    client.post(
        "/api/v1/admin/tenants/acme/schedule-delete",
        json={"grace_days": 3},
        headers=_hdr("key-admin"),
    )
    client.delete(
        "/api/v1/admin/tenants/acme/schedule-delete",
        headers=_hdr("key-admin"),
    )
    r = client.get("/api/v1/memories", headers=_hdr("key-acme"))
    assert r.status_code == 200


# ----------------------------------------------------------------- reaper


def _seed_tenant(global_root: Path, tenant_id: str, *, content: str) -> Path:
    """Drop a markdown file and return the tenant dir."""
    tdir = global_root / tenant_id
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{tenant_id}.md").write_text(
        f"---\ntitle: {tenant_id}\n---\n{content}\n", encoding="utf-8"
    )
    return tdir


def _backdate(tenant_dir: Path, *, days_ago: int) -> None:
    """Rewrite the tombstone with a delete_after in the past so the
    reaper treats it as expired."""
    path = tombstone_path(tenant_dir)
    body = json.loads(path.read_text(encoding="utf-8"))
    delete_after = datetime.now(timezone.utc) - timedelta(days=days_ago)
    body["delete_after"] = delete_after.isoformat()
    body["scheduled_at"] = (delete_after - timedelta(days=7)).isoformat()
    path.write_text(json.dumps(body, sort_keys=True, indent=2), encoding="utf-8")


def test_reaper_skips_non_tombstoned(global_root, capsys):
    from memograph.scripts.run_reaper import reap_once

    _seed_tenant(global_root, "alive", content="hello")
    failures = reap_once(global_root)
    assert failures == 0
    assert (global_root / "alive").exists()


def test_reaper_skips_pending_tombstone(global_root, capsys):
    from memograph.scripts.run_reaper import reap_once

    tdir = _seed_tenant(global_root, "soon", content="x")
    write_tombstone(tdir, requested_by="op", grace_days=30)

    failures = reap_once(global_root)
    assert failures == 0
    assert tdir.exists()  # not yet destroyed

    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.strip().splitlines() if line]
    assert any(e["event"] == "tombstone_pending" for e in events)


def test_reaper_destroys_expired_and_writes_backup(global_root, capsys):
    from memograph.scripts.run_reaper import reap_once

    tdir = _seed_tenant(global_root, "expired", content="secret-payload")
    write_tombstone(tdir, requested_by="op", grace_days=0)
    _backdate(tdir, days_ago=1)

    failures = reap_once(global_root)
    assert failures == 0
    assert not tdir.exists()

    exports = list((global_root / ".tombstoned-exports").glob("expired-*.tar.gz"))
    assert len(exports) == 1
    # Verify the backup contains the markdown content.
    with tarfile.open(exports[0], "r:gz") as tar:
        names = tar.getnames()
        md_files = [n for n in names if n.endswith(".md")]
        assert md_files, f"no markdown files in {names!r}"
        member = tar.getmember(md_files[0])
        f = tar.extractfile(member)
        assert f is not None
        body = f.read().decode("utf-8")
        assert "secret-payload" in body

    # Stdout should contain a "destroyed" event.
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.strip().splitlines()
        if line
    ]
    destroyed = [e for e in events if e["event"] == "destroyed"]
    assert len(destroyed) == 1
    assert destroyed[0]["tenant_id"] == "expired"


def test_reaper_dry_run_destroys_nothing(global_root, capsys):
    from memograph.scripts.run_reaper import reap_once

    tdir = _seed_tenant(global_root, "doomed", content="x")
    write_tombstone(tdir, requested_by="op", grace_days=0)
    _backdate(tdir, days_ago=1)

    failures = reap_once(global_root, dry_run=True)
    assert failures == 0
    assert tdir.exists()  # untouched in dry-run
    assert not (global_root / ".tombstoned-exports").exists() or not list(
        (global_root / ".tombstoned-exports").iterdir()
    )

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.strip().splitlines()
        if line
    ]
    assert any(e["event"] == "would_destroy" for e in events)


def test_reaper_reports_corrupted_tombstone(global_root, capsys):
    from memograph.scripts.run_reaper import reap_once

    tdir = _seed_tenant(global_root, "broken", content="x")
    (tdir / TOMBSTONE_FILENAME).write_text("not-json", encoding="utf-8")

    failures = reap_once(global_root)
    assert failures == 1
    assert tdir.exists()  # we don't silently destroy on corruption

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.strip().splitlines()
        if line
    ]
    assert any(e["event"] == "tombstone_corrupted" for e in events)


def test_reaper_processes_multiple_tenants(global_root, capsys):
    from memograph.scripts.run_reaper import reap_once

    a = _seed_tenant(global_root, "ta", content="a")
    write_tombstone(a, requested_by="op", grace_days=0)
    _backdate(a, days_ago=1)

    _seed_tenant(global_root, "tb", content="b")  # no tombstone

    c = _seed_tenant(global_root, "tc", content="c")
    write_tombstone(c, requested_by="op", grace_days=30)

    failures = reap_once(global_root)
    assert failures == 0
    assert not a.exists()
    assert (global_root / "tb").exists()
    assert c.exists()


def test_reaper_main_returns_zero_on_clean_run(tmp_path, monkeypatch):
    """The CLI entry point exits 0 when the sweep had no failures."""
    from memograph.scripts.run_reaper import main

    rv = main([str(tmp_path)])
    assert rv == 0


def test_reaper_main_returns_nonzero_on_missing_root(tmp_path):
    from memograph.scripts.run_reaper import main

    rv = main([str(tmp_path / "missing")])
    assert rv == 2
