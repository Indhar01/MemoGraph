"""OpenAPI contract snapshot for the /api/v1 surface.

Fails loudly if any route is added, removed, or changes verb on the
canonical /api/v1 prefix. The snapshot is just the sorted list of
``"<METHOD> <path>"`` entries — schema-level diffing is out of scope
for Phase 1 (Phase 4 productization will deepen it).

When the contract intentionally changes:

    MEMOGRAPH_UPDATE_OPENAPI_SNAPSHOT=1 pytest tests/contract/

regenerates the snapshot file. Always review the resulting diff in code
review — that is the *point* of this test.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from memograph.web.backend.server import create_app  # noqa: E402

SNAPSHOT_PATH = Path(__file__).with_name("openapi_v1.snapshot.json")
UPDATE_SNAPSHOT = os.environ.get("MEMOGRAPH_UPDATE_OPENAPI_SNAPSHOT", "").lower() in {
    "1",
    "true",
    "yes",
}


@pytest.fixture
def openapi_doc(tmp_path) -> dict:
    vault = tmp_path / "vault"
    vault.mkdir()
    app = create_app(vault_path=str(vault), use_gam=False)
    app.state.kernel.ingest()
    app.state.is_ready = True
    client = TestClient(app)
    return client.get("/api/openapi.json").json()


def _v1_routes(doc: dict) -> list[str]:
    """Sorted list of "<METHOD> <path>" entries for /api/v1 paths only."""
    paths = doc.get("paths", {})
    routes = []
    for path, ops in paths.items():
        if not path.startswith("/api/v1/"):
            continue
        for method in ops:
            if method.lower() in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "options",
                "head",
            }:
                routes.append(f"{method.upper()} {path}")
    return sorted(routes)


def test_openapi_snapshot_matches(openapi_doc):
    actual = _v1_routes(openapi_doc)

    if UPDATE_SNAPSHOT:
        SNAPSHOT_PATH.write_text(
            json.dumps({"routes": actual}, indent=2) + "\n",
            encoding="utf-8",
        )
        pytest.skip(
            f"Snapshot updated at {SNAPSHOT_PATH.name}. " "Review the diff in your PR."
        )

    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            f"Missing snapshot at {SNAPSHOT_PATH}. "
            "Run with MEMOGRAPH_UPDATE_OPENAPI_SNAPSHOT=1 to create it."
        )

    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["routes"]

    added = sorted(set(actual) - set(expected))
    removed = sorted(set(expected) - set(actual))
    if added or removed:
        msg = ["OpenAPI /api/v1 contract drift detected:"]
        if added:
            msg.append(f"  added: {added}")
        if removed:
            msg.append(f"  removed: {removed}")
        msg.append(
            "If the change is intentional, regenerate the snapshot with: "
            "MEMOGRAPH_UPDATE_OPENAPI_SNAPSHOT=1 pytest tests/contract/"
        )
        pytest.fail("\n".join(msg))


def test_v1_health_route_in_doc(openapi_doc):
    """Sanity check that /api/v1 is actually being mounted at all."""
    paths = openapi_doc.get("paths", {})
    assert any(
        p.startswith("/api/v1/") for p in paths
    ), "no /api/v1/ paths in OpenAPI doc — versioning is broken"
