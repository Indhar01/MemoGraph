"""Tests for MemoGraph MCP server.

Validates:
- Server initialization and auto-ingest
- Tool schema completeness
- Tool routing (all tools are routable)
- Core tool functionality: search, create, get, list, update, delete
- Autonomous hooks: query, response, configure, get config
- Error handling for invalid inputs
"""

from pathlib import Path

import pytest

from memograph.mcp.server import MemoGraphMCPServer


@pytest.fixture
def temp_vault(tmp_path):
    """Create a temporary vault directory with test memories."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def mcp_server(temp_vault):
    """Create an MCP server instance with a temp vault."""
    server = MemoGraphMCPServer(vault_path=str(temp_vault))
    return server


@pytest.fixture
def populated_server(temp_vault):
    """Create an MCP server with pre-populated memories."""
    # Create some test memory files
    for i, (title, content, tags) in enumerate(
        [
            (
                "Python Tips",
                "Use list comprehensions for cleaner code",
                ["python", "tips"],
            ),
            ("Docker Guide", "Container basics and setup", ["docker", "devops"]),
            ("ML Basics", "Introduction to machine learning", ["ml", "ai", "python"]),
        ]
    ):
        slug = title.lower().replace(" ", "-")
        (temp_vault / f"{slug}.md").write_text(
            f"---\ntitle: {title}\nmemory_type: semantic\n"
            f"salience: 0.7\ntags: {tags}\n---\n\n{content}\n",
            encoding="utf-8",
        )

    server = MemoGraphMCPServer(vault_path=str(temp_vault))
    return server


class TestServerInitialization:
    """Test server initialization."""

    def test_basic_init(self, mcp_server, temp_vault):
        """Test basic server initialization."""
        assert mcp_server.vault_path == Path(temp_vault)
        assert mcp_server.kernel is not None

    def test_auto_ingest_on_startup(self, populated_server):
        """Test that vault is auto-ingested on startup."""
        nodes = populated_server.kernel.graph.all_nodes()
        assert len(nodes) == 3

    def test_server_info(self, mcp_server):
        """Test get_server_info returns correct metadata."""
        info = mcp_server.get_server_info()
        assert info["name"] == "MemoGraph MCP Server"
        assert "vault" in info
        assert "capabilities" in info

    def test_server_version_matches_package(self, mcp_server):
        """Test that server version matches package version."""
        import memograph

        info = mcp_server.get_server_info()
        assert info["version"] == memograph.__version__


class TestToolSchema:
    """Test tool schema completeness."""

    def test_tools_schema_returns_list(self, mcp_server):
        """Test that get_tools_schema returns a list."""
        schemas = mcp_server.get_tools_schema()
        assert isinstance(schemas, list)
        assert len(schemas) == 19

    def test_all_tools_have_required_fields(self, mcp_server):
        """Test that all tool schemas have name, description, inputSchema."""
        for schema in mcp_server.get_tools_schema():
            assert "name" in schema, "Missing 'name' in tool schema"
            assert "description" in schema, (
                f"Missing 'description' in {schema.get('name')}"
            )
            assert "inputSchema" in schema, (
                f"Missing 'inputSchema' in {schema.get('name')}"
            )
            assert schema["inputSchema"]["type"] == "object"

    def test_all_tool_names_are_routable(self, mcp_server):
        """Test that every tool in schema has a corresponding server method."""
        tool_names = [t["name"] for t in mcp_server.get_tools_schema()]
        for name in tool_names:
            # Check that the method exists on the server
            method_name = name
            assert hasattr(mcp_server, method_name), (
                f"Tool '{name}' has no corresponding method on MemoGraphMCPServer"
            )


class TestSearchTool:
    """Test search_vault tool."""

    @pytest.mark.asyncio
    async def test_search_empty_vault(self, mcp_server):
        """Test searching an empty vault."""
        result = await mcp_server.search_vault(query="test")
        assert result["success"] is True
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_search_populated_vault(self, populated_server):
        """Test searching a populated vault."""
        result = await populated_server.search_vault(query="python")
        assert result["success"] is True
        assert result["count"] > 0
        assert "vault_context" in result

    @pytest.mark.asyncio
    async def test_search_with_memory_type_filter(self, populated_server):
        """Test searching with memory type filter."""
        result = await populated_server.search_vault(
            query="python", memory_type="semantic"
        )
        assert result["success"] is True


class TestCreateTool:
    """Test create_memory tool."""

    @pytest.mark.asyncio
    async def test_create_memory(self, mcp_server):
        """Test creating a memory."""
        result = await mcp_server.create_memory(
            title="Test Memory",
            content="This is test content",
            tags=["test"],
        )
        assert result["success"] is True
        assert "path" in result
        assert Path(result["path"]).exists()

    @pytest.mark.asyncio
    async def test_create_memory_with_type(self, mcp_server):
        """Test creating a memory with specific type."""
        result = await mcp_server.create_memory(
            title="Meeting Notes",
            content="Discussed project plan",
            memory_type="episodic",
            salience=0.9,
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_memory_invalid_type(self, mcp_server):
        """Test creating a memory with invalid type."""
        result = await mcp_server.create_memory(
            title="Test",
            content="Content",
            memory_type="invalid_type",
        )
        assert result["success"] is False


class TestReadTools:
    """Test get_memory, list_memories, get_vault_info, get_vault_stats tools."""

    @pytest.mark.asyncio
    async def test_list_memories(self, populated_server):
        """Test listing memories."""
        result = await populated_server.list_memories()
        assert result["success"] is True
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_list_memories_with_limit(self, populated_server):
        """Test listing with limit."""
        result = await populated_server.list_memories(limit=1)
        assert result["success"] is True
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_get_memory(self, populated_server):
        """Test getting a specific memory."""
        # First list to get an ID
        list_result = await populated_server.list_memories()
        memory_id = list_result["memories"][0]["id"]

        result = await populated_server.get_memory(memory_id=memory_id)
        assert result["success"] is True
        assert "memory" in result
        assert result["memory"]["id"] == memory_id

    @pytest.mark.asyncio
    async def test_get_memory_not_found(self, mcp_server):
        """Test getting a nonexistent memory."""
        result = await mcp_server.get_memory(memory_id="nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_vault_info(self, mcp_server):
        """Test getting vault info."""
        result = await mcp_server.get_vault_info()
        assert result["success"] is True
        assert "vault" in result

    @pytest.mark.asyncio
    async def test_get_vault_stats(self, populated_server):
        """Test getting vault stats."""
        result = await populated_server.get_vault_stats()
        assert result["success"] is True
        assert result["total_memories"] == 3


class TestUpdateTool:
    """Test update_memory tool."""

    @pytest.mark.asyncio
    async def test_update_salience(self, populated_server):
        """Test updating memory salience."""
        list_result = await populated_server.list_memories()
        memory_id = list_result["memories"][0]["id"]

        result = await populated_server.update_memory(
            memory_id=memory_id, salience=0.95
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_not_found(self, mcp_server):
        """Test updating nonexistent memory."""
        result = await mcp_server.update_memory(memory_id="nonexistent", salience=0.5)
        assert result["success"] is False


class TestDeleteTool:
    """Test delete_memory tool."""

    @pytest.mark.asyncio
    async def test_delete_memory(self, populated_server):
        """Test deleting a memory."""
        list_result = await populated_server.list_memories()
        memory_id = list_result["memories"][0]["id"]

        result = await populated_server.delete_memory(memory_id=memory_id)
        assert result["success"] is True

        # Verify it's gone from the graph
        assert populated_server.kernel.graph.get(memory_id) is None

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mcp_server):
        """Test deleting nonexistent memory."""
        result = await mcp_server.delete_memory(memory_id="nonexistent")
        assert result["success"] is False


class TestImportTool:
    """Test import_document tool."""

    @pytest.mark.asyncio
    async def test_import_txt_file(self, mcp_server, tmp_path):
        """Test importing a .txt file."""
        test_file = tmp_path / "test-doc.txt"
        test_file.write_text("This is imported content", encoding="utf-8")

        result = await mcp_server.import_document(file_path=str(test_file))
        assert result["success"] is True
        assert "path" in result

    @pytest.mark.asyncio
    async def test_import_md_file(self, mcp_server, tmp_path):
        """Test importing a .md file."""
        test_file = tmp_path / "notes.md"
        test_file.write_text("# My Notes\n\nSome content here", encoding="utf-8")

        result = await mcp_server.import_document(
            file_path=str(test_file), tags=["imported"]
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_import_nonexistent_file(self, mcp_server):
        """Test importing a nonexistent file."""
        result = await mcp_server.import_document(file_path="/nonexistent/file.txt")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_import_unsupported_type(self, mcp_server, tmp_path):
        """Test importing unsupported file type."""
        test_file = tmp_path / "test.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        result = await mcp_server.import_document(file_path=str(test_file))
        assert result["success"] is False
        assert "Unsupported" in result["error"]


class TestAutonomousHooks:
    """Test autonomous hook tools."""

    @pytest.mark.asyncio
    async def test_get_autonomous_config(self, mcp_server):
        """Test getting autonomous configuration."""
        result = await mcp_server.get_autonomous_config()
        assert "auto_search_enabled" in result
        assert "auto_save_responses" in result

    @pytest.mark.asyncio
    async def test_configure_autonomous_mode(self, mcp_server):
        """Test configuring autonomous mode."""
        result = await mcp_server.configure_autonomous_mode(
            auto_search=True, auto_save_responses=True
        )
        assert result["success"] is True

        config = await mcp_server.get_autonomous_config()
        assert config["auto_search_enabled"] is True

    @pytest.mark.asyncio
    async def test_auto_hook_query_short_query(self, mcp_server):
        """Test auto hook with query too short."""
        result = await mcp_server.auto_hook_query(user_query="hi")
        assert result["success"] is True
        assert result["context"] is None

    @pytest.mark.asyncio
    async def test_auto_hook_query_with_search(self, populated_server):
        """Test auto hook with search enabled."""
        await populated_server.configure_autonomous_mode(auto_search=True)

        result = await populated_server.auto_hook_query(
            user_query="Tell me about Python programming"
        )
        assert result["success"] is True
        assert "searched_vault" in result["actions"]

    @pytest.mark.asyncio
    async def test_auto_hook_response(self, mcp_server):
        """Test auto hook response saves conversation."""
        result = await mcp_server.auto_hook_response(
            user_query="What is Python?",
            ai_response="Python is a programming language.",
        )
        assert result["success"] is True
        assert result["saved"] is True
        assert "path" in result

    @pytest.mark.asyncio
    async def test_auto_hook_response_disabled(self, mcp_server):
        """Test auto hook response when disabled."""
        await mcp_server.configure_autonomous_mode(auto_save_responses=False)

        result = await mcp_server.auto_hook_response(
            user_query="test", ai_response="response"
        )
        assert result["saved"] is False


class TestListAvailableTools:
    """Test list_available_tools tool."""

    @pytest.mark.asyncio
    async def test_list_tools(self, mcp_server):
        """Test listing available tools."""
        result = await mcp_server.list_available_tools()
        assert result["success"] is True
        assert result["total_tools"] == 19
        assert "categories" in result
        assert "autonomous" in result["categories"]
        assert "graph" in result["categories"]
        assert "bulk" in result["categories"]


class TestGraphTools:
    """Test graph-native tools."""

    @pytest.mark.asyncio
    async def test_search_by_graph(self, populated_server):
        """Test searching by graph traversal."""
        nodes = populated_server.kernel.graph.all_nodes()
        memory_id = nodes[0].id

        result = await populated_server.search_by_graph(memory_id=memory_id)
        assert result["success"] is True
        assert "center" in result
        assert result["center"]["id"] == memory_id

    @pytest.mark.asyncio
    async def test_search_by_graph_not_found(self, mcp_server):
        """Test graph search for nonexistent memory."""
        result = await mcp_server.search_by_graph(memory_id="nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_relate_memories(self, populated_server):
        """Test creating a link between memories."""
        nodes = populated_server.kernel.graph.all_nodes()
        if len(nodes) < 2:
            pytest.skip("Need at least 2 memories")

        source_id = nodes[0].id
        target_id = nodes[1].id

        result = await populated_server.relate_memories(
            source_id=source_id, target_id=target_id, relationship="related to"
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_relate_memories_not_found(self, mcp_server):
        """Test relating nonexistent memories."""
        result = await mcp_server.relate_memories(
            source_id="nonexistent", target_id="also-nonexistent"
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_find_path(self, populated_server):
        """Test finding path between memories."""
        nodes = populated_server.kernel.graph.all_nodes()
        if len(nodes) < 2:
            pytest.skip("Need at least 2 memories")

        result = await populated_server.find_path(
            from_id=nodes[0].id, to_id=nodes[1].id
        )
        assert result["success"] is True
        # Path may or may not exist depending on links

    @pytest.mark.asyncio
    async def test_find_path_same_node(self, populated_server):
        """Test finding path from node to itself."""
        nodes = populated_server.kernel.graph.all_nodes()
        result = await populated_server.find_path(
            from_id=nodes[0].id, to_id=nodes[0].id
        )
        assert result["success"] is True
        assert result["path_found"] is True
        assert result["path_length"] == 1


class TestBulkCreate:
    """Test bulk_create tool."""

    @pytest.mark.asyncio
    async def test_bulk_create(self, mcp_server):
        """Test creating multiple memories at once."""
        memories = [
            {"title": "Bulk Note 1", "content": "First bulk note"},
            {"title": "Bulk Note 2", "content": "Second bulk note"},
            {"title": "Bulk Note 3", "content": "Third bulk note"},
        ]
        result = await mcp_server.bulk_create(memories=memories)
        assert result["success"] is True
        assert result["created"] == 3
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_bulk_create_with_errors(self, mcp_server):
        """Test bulk create with some invalid entries."""
        memories = [
            {"title": "Good Note", "content": "Valid content"},
            {"title": "", "content": "Invalid title"},
        ]
        result = await mcp_server.bulk_create(memories=memories)
        assert result["success"] is True
        assert result["created"] == 1
        assert result["failed"] == 1


class TestCreateMemorySuggestions:
    """Test that create_memory returns suggested links."""

    @pytest.mark.asyncio
    async def test_suggested_links(self, populated_server):
        """Test that creating a memory returns link suggestions."""
        result = await populated_server.create_memory(
            title="Python Testing Guide",
            content="How to test Python code",
            tags=["python", "testing"],
        )
        assert result["success"] is True
        assert "suggested_links" in result
        # Should suggest linking to "Python Tips" due to shared "python" tag
        if result["suggested_links"]:
            assert any(
                "python" in link.get("reason", "").lower()
                for link in result["suggested_links"]
            )
