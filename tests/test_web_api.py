"""Tests for MemoGraph Web API (FastAPI backend).

Tests the REST API endpoints for memories, search, graph, and analytics.
Requires: pip install memograph[web]
"""

import pytest

try:
    from fastapi.testclient import TestClient

    from memograph.web.backend.server import create_app

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")


@pytest.fixture
def temp_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def populated_vault(temp_vault):
    for title, content, tags in [
        ("Python Tips", "Use list comprehensions for cleaner code", ["python", "tips"]),
        (
            "Docker Guide",
            "Container basics and setup instructions",
            ["docker", "devops"],
        ),
        (
            "ML Basics",
            "Introduction to machine learning concepts",
            ["ml", "ai", "python"],
        ),
    ]:
        slug = title.lower().replace(" ", "-")
        tag_list = str(tags)
        (temp_vault / f"{slug}.md").write_text(
            f"---\ntitle: {title}\nmemory_type: semantic\n"
            f"salience: 0.7\ntags: {tag_list}\n---\n\n{content}\n",
            encoding="utf-8",
        )
    return temp_vault


@pytest.fixture
def client(populated_vault):
    app = create_app(vault_path=str(populated_vault), use_gam=False)
    # Manually ingest since TestClient may not trigger async lifespan
    app.state.kernel.ingest()
    return TestClient(app)


@pytest.fixture
def empty_client(temp_vault):
    app = create_app(vault_path=str(temp_vault), use_gam=False)
    return TestClient(app)


class TestHealthEndpoints:
    """Test health and root endpoints."""

    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "MemoGraph API"

    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["total_memories"] == 3


class TestMemoriesAPI:
    """Test /api/memories endpoints."""

    def test_list_memories(self, client):
        response = client.get("/api/memories")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["memories"]) == 3

    def test_list_memories_pagination(self, client):
        response = client.get("/api/memories?page=1&page_size=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["memories"]) == 2
        assert data["has_more"] is True

    def test_get_memory(self, client):
        # First get list to find an ID
        list_response = client.get("/api/memories")
        memory_id = list_response.json()["memories"][0]["id"]

        response = client.get(f"/api/memories/{memory_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == memory_id

    def test_get_memory_not_found(self, client):
        response = client.get("/api/memories/nonexistent-id")
        assert response.status_code == 404

    def test_create_memory(self, client):
        response = client.post(
            "/api/memories",
            json={
                "title": "New Memory",
                "content": "Created via API",
                "memory_type": "fact",
                "tags": ["api", "test"],
                "salience": 0.8,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "message" in data

    def test_create_memory_validation(self, client):
        response = client.post(
            "/api/memories",
            json={"title": "", "content": "Missing title"},
        )
        assert response.status_code == 422  # Validation error

    def test_delete_memory(self, client):
        list_response = client.get("/api/memories")
        memory_id = list_response.json()["memories"][0]["id"]

        response = client.delete(f"/api/memories/{memory_id}")
        assert response.status_code == 200

        # Verify deleted
        get_response = client.get(f"/api/memories/{memory_id}")
        assert get_response.status_code == 404


class TestSearchAPI:
    """Test /api/search endpoint."""

    def test_search(self, client):
        response = client.post(
            "/api/search",
            json={"query": "python", "top_k": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert data["total"] >= 0
        assert "execution_time_ms" in data

    def test_search_with_filters(self, client):
        response = client.post(
            "/api/search",
            json={
                "query": "docker",
                "memory_type": "semantic",
                "min_salience": 0.5,
            },
        )
        assert response.status_code == 200

    def test_search_empty_query(self, client):
        response = client.post("/api/search", json={"query": ""})
        assert response.status_code == 422


class TestGraphAPI:
    """Test /api/graph endpoint."""

    def test_get_graph(self, client):
        response = client.get("/api/graph")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data
        assert data["total_nodes"] == 3


class TestAnalyticsAPI:
    """Test /api/analytics endpoint."""

    def test_get_analytics(self, client):
        response = client.get("/api/analytics")
        assert response.status_code == 200
        data = response.json()
        assert data["total_memories"] == 3
        assert "tag_distribution" in data
        assert "memory_type_distribution" in data
