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
        assert (
            len(schemas) == 42
        )  # +auto_hook_turn, configure_capture_mode, get_capture_mode

    def test_all_tools_have_required_fields(self, mcp_server):
        """Test that all tool schemas have name, description, inputSchema."""
        for schema in mcp_server.get_tools_schema():
            assert "name" in schema, "Missing 'name' in tool schema"
            assert (
                "description" in schema
            ), f"Missing 'description' in {schema.get('name')}"
            assert (
                "inputSchema" in schema
            ), f"Missing 'inputSchema' in {schema.get('name')}"
            assert schema["inputSchema"]["type"] == "object"

    def test_all_tool_names_are_routable(self, mcp_server):
        """Test that every tool in schema has a corresponding server method."""
        tool_names = [t["name"] for t in mcp_server.get_tools_schema()]
        for name in tool_names:
            # Check that the method exists on the server
            method_name = name
            assert hasattr(
                mcp_server, method_name
            ), f"Tool '{name}' has no corresponding method on MemoGraphMCPServer"


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
        assert (
            result["total_tools"] == 42
        )  # +auto_hook_turn, configure_capture_mode, get_capture_mode
        assert "categories" in result
        assert "autonomous" in result["categories"]
        assert "graph" in result["categories"]
        assert "bulk" in result["categories"]


class TestVerificationTools:
    """Test verification tools for auto-save."""

    @pytest.mark.asyncio
    async def test_verify_last_save_no_saves(self, mcp_server):
        """Test verify_last_save when no saves exist."""
        result = await mcp_server.verify_last_save()
        assert result["success"] is True
        assert result["found_recent_save"] is False
        assert "troubleshooting_tips" in result

    @pytest.mark.asyncio
    async def test_verify_last_save_with_recent_save(self, mcp_server):
        """Test verify_last_save after making a save."""
        # First create a conversation memory
        await mcp_server.auto_hook_response(
            user_query="Test question", ai_response="Test answer"
        )

        # Now verify it
        result = await mcp_server.verify_last_save(time_window_seconds=60)
        assert result["success"] is True
        assert result["found_recent_save"] is True
        assert "last_save" in result
        assert result["last_save"]["seconds_ago"] < 10

    @pytest.mark.asyncio
    async def test_verify_last_save_old_save(self, mcp_server):
        """Test verify_last_save with very short time window."""
        await mcp_server.auto_hook_response(
            user_query="Old question", ai_response="Old answer"
        )

        # Wait at least 1 second then check with 0 second window
        import asyncio

        await asyncio.sleep(1.1)

        result = await mcp_server.verify_last_save(time_window_seconds=0)
        assert result["success"] is True
        assert result["found_recent_save"] is False

    @pytest.mark.asyncio
    async def test_get_save_stats_no_attempts(self, mcp_server):
        """Test get_save_stats with no save attempts."""
        result = await mcp_server.get_save_stats()
        assert result["success"] is True
        assert result["statistics"]["save_attempts"] == 0
        assert result["statistics"]["save_rate_percent"] == 0.0

    @pytest.mark.asyncio
    async def test_get_save_stats_with_saves(self, mcp_server):
        """Test get_save_stats after multiple saves."""
        # Make several saves
        for i in range(5):
            await mcp_server.auto_hook_response(
                user_query=f"Question {i}", ai_response=f"Answer {i}"
            )

        result = await mcp_server.get_save_stats(period="session")
        assert result["success"] is True
        assert result["statistics"]["save_attempts"] == 5
        assert result["statistics"]["successful_saves"] == 5
        assert result["statistics"]["save_rate_percent"] == 100.0
        assert result["interpretation"]["status"] in ["excellent", "good"]

    @pytest.mark.asyncio
    async def test_get_save_stats_different_periods(self, mcp_server):
        """Test get_save_stats with different time periods."""
        await mcp_server.auto_hook_response(user_query="Test", ai_response="Response")

        for period in ["session", "hour", "day", "week", "all"]:
            result = await mcp_server.get_save_stats(period=period)
            assert result["success"] is True
            assert result["period"] == period

    @pytest.mark.asyncio
    async def test_get_save_stats_invalid_period(self, mcp_server):
        """Test get_save_stats with invalid period."""
        result = await mcp_server.get_save_stats(period="invalid")
        assert result["success"] is False
        assert "Invalid period" in result["error"]


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


# ==================== Phase 3 Tests ====================


class TestPhase3Analytics:
    """Test Phase 3 auto-save analytics functionality."""

    @pytest.mark.asyncio
    async def test_get_auto_save_analytics_empty_vault(self, mcp_server):
        """Test analytics with no conversation memories."""
        result = await mcp_server.get_auto_save_analytics(period="day")
        assert result["success"] is True
        assert result["period"] == "day"
        assert result["summary"]["total_conversations_saved"] == 0
        assert "performance_grade" in result
        assert "by_layer" in result

    @pytest.mark.asyncio
    async def test_get_auto_save_analytics_with_saves(self, mcp_server):
        """Test analytics after creating conversation memories."""
        # Create some Layer 1 saves
        for i in range(3):
            await mcp_server.auto_hook_response(
                user_query=f"Question {i}?", ai_response=f"Answer {i}"
            )

        result = await mcp_server.get_auto_save_analytics(period="day")
        assert result["success"] is True
        assert result["summary"]["total_conversations_saved"] == 3
        assert result["by_layer"]["layer1_explicit_saves"] == 3
        assert result["by_layer"]["layer2_monitor_saves"] == 0

    @pytest.mark.asyncio
    async def test_analytics_performance_grading(self, mcp_server):
        """Test that performance grades are calculated correctly."""
        # Create enough saves for good performance
        for i in range(10):
            await mcp_server.auto_hook_response(
                user_query=f"Test {i}", ai_response=f"Response {i}"
            )

        result = await mcp_server.get_auto_save_analytics(period="day")
        assert result["success"] is True
        grade = result["performance_grade"]
        assert "grade" in grade
        assert "status" in grade
        # Emoji removed in 0.4.1 to drop UI noise from the API response.
        assert "emoji" not in grade
        # With 10 saves, should have good grade
        assert grade["grade"] in ["A+", "A", "B"]

    @pytest.mark.asyncio
    async def test_analytics_recommendations(self, mcp_server):
        """Test that analytics provides recommendations."""
        result = await mcp_server.get_auto_save_analytics(
            period="day", include_recommendations=True
        )
        assert result["success"] is True
        assert "recommendations" in result
        assert isinstance(result["recommendations"], list)

    @pytest.mark.asyncio
    async def test_analytics_no_recommendations(self, mcp_server):
        """Test analytics without recommendations."""
        result = await mcp_server.get_auto_save_analytics(
            period="day", include_recommendations=False
        )
        assert result["success"] is True
        assert "recommendations" not in result

    @pytest.mark.asyncio
    async def test_analytics_different_periods(self, mcp_server):
        """Test analytics with different time periods."""
        await mcp_server.auto_hook_response(user_query="Test", ai_response="Response")

        for period in ["hour", "day", "week", "all"]:
            result = await mcp_server.get_auto_save_analytics(period=period)
            assert result["success"] is True
            assert result["period"] == period
            assert "time_window" in result

    @pytest.mark.asyncio
    async def test_analytics_layer_differentiation(self, mcp_server):
        """Test that analytics differentiates between Layer 1 and Layer 2."""
        # Create Layer 1 save
        await mcp_server.auto_hook_response(
            user_query="Layer 1 test", ai_response="Layer 1 response"
        )

        # Manually create a Layer 2 save (simulating monitor save)
        from memograph.core.enums import MemoryType

        mcp_server.kernel.remember(
            title="Auto-detected: Layer 2 test",
            content="**Saved By:** Layer 2 (Server Monitor)\n\nTest content",
            memory_type=MemoryType.EPISODIC,
            tags=["conversation", "monitor-layer2", "auto-detected"],
        )
        mcp_server.kernel.ingest()

        result = await mcp_server.get_auto_save_analytics(period="day")
        assert result["success"] is True
        assert result["by_layer"]["layer1_explicit_saves"] >= 1
        assert result["by_layer"]["layer2_monitor_saves"] >= 1

    @pytest.mark.asyncio
    async def test_analytics_time_window_calculation(self, mcp_server):
        """Test that time window is calculated correctly."""
        result = await mcp_server.get_auto_save_analytics(period="day")
        assert result["success"] is True
        assert "time_window" in result
        assert "start" in result["time_window"]
        assert "end" in result["time_window"]
        assert "duration_hours" in result["time_window"]
        # Day should be ~24 hours
        assert result["time_window"]["duration_hours"] >= 23


class TestPhase3EnhancedNotifications:
    """Test Phase 3 enhanced notification messages."""

    @pytest.mark.asyncio
    async def test_auto_hook_response_enhanced_message(self, mcp_server):
        """Test that auto_hook_response returns enhanced message."""
        result = await mcp_server.auto_hook_response(
            user_query="Test question", ai_response="Test answer"
        )
        assert result["success"] is True
        assert "layer" in result
        assert result["layer"] == "layer1"
        assert "tip" in result
        assert "Layer 1" in result["message"]

    @pytest.mark.asyncio
    async def test_layer1_saves_have_proper_tags(self, mcp_server):
        """Test that Layer 1 saves include layer1-explicit tag."""
        await mcp_server.auto_hook_response(
            user_query="Tag test", ai_response="Tag response"
        )

        # Check the saved memory has the tag
        mcp_server.kernel.ingest()
        nodes = mcp_server.kernel.graph.all_nodes()
        conversation_nodes = [n for n in nodes if "conversation" in n.tags]
        assert len(conversation_nodes) >= 1
        assert "layer1-explicit" in conversation_nodes[0].tags

    @pytest.mark.asyncio
    async def test_layer1_saves_have_metadata(self, mcp_server):
        """Test that Layer 1 saves include 'Saved By' metadata."""
        await mcp_server.auto_hook_response(
            user_query="Metadata test", ai_response="Metadata response"
        )

        # Check the saved memory has the metadata
        mcp_server.kernel.ingest()
        nodes = mcp_server.kernel.graph.all_nodes()
        conversation_nodes = [n for n in nodes if "conversation" in n.tags]
        assert len(conversation_nodes) >= 1
        assert (
            "**Saved By:** Layer 1 (AI Explicit Save)" in conversation_nodes[0].content
        )


class TestPhase3ToolCount:
    """Test that Phase 3 adds get_auto_save_analytics tool."""

    def test_tool_count_includes_analytics(self, mcp_server):
        """Test that tool count reflects all available tools."""
        schemas = mcp_server.get_tools_schema()
        # Updated to reflect current tool count
        assert len(schemas) == 42

    def test_get_auto_save_analytics_tool_in_schema(self, mcp_server):
        """Test that get_auto_save_analytics is in tool schema."""
        schemas = mcp_server.get_tools_schema()
        tool_names = [s["name"] for s in schemas]
        assert "get_auto_save_analytics" in tool_names

    def test_analytics_tool_has_proper_schema(self, mcp_server):
        """Test that analytics tool has proper schema."""
        schemas = mcp_server.get_tools_schema()
        analytics_schema = next(
            s for s in schemas if s["name"] == "get_auto_save_analytics"
        )

        assert "description" in analytics_schema
        assert "📊" in analytics_schema["description"]
        assert "inputSchema" in analytics_schema
        assert "period" in analytics_schema["inputSchema"]["properties"]
        assert (
            "include_recommendations" in analytics_schema["inputSchema"]["properties"]
        )


class TestReadOnlyMode:
    """MEMOGRAPH_READONLY=true must refuse vault-writing tools but keep reads working."""

    @pytest.fixture
    def readonly_server(self, temp_vault, monkeypatch):
        for i, (title, content, tags) in enumerate(
            [
                ("Note A", "first note body", ["a"]),
                ("Note B", "second note body", ["b"]),
            ]
        ):
            slug = title.lower().replace(" ", "-")
            (temp_vault / f"{slug}.md").write_text(
                f"---\ntitle: {title}\nmemory_type: semantic\n"
                f"salience: 0.7\ntags: {tags}\n---\n\n{content}\n",
                encoding="utf-8",
            )
        monkeypatch.setenv("MEMOGRAPH_READONLY", "true")
        return MemoGraphMCPServer(vault_path=str(temp_vault))

    def test_readonly_flag_is_set(self, readonly_server):
        assert readonly_server.readonly is True

    @pytest.mark.asyncio
    async def test_create_memory_refused(self, readonly_server):
        result = await readonly_server.create_memory(
            title="blocked", content="should not save"
        )
        assert result["success"] is False
        assert result.get("readonly") is True
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_delete_memory_refused(self, readonly_server):
        listed = await readonly_server.list_memories()
        memory_id = listed["memories"][0]["id"]
        result = await readonly_server.delete_memory(memory_id=memory_id)
        assert result["success"] is False
        assert result.get("readonly") is True
        # Memory must still exist after the refused delete.
        assert readonly_server.kernel.graph.get(memory_id) is not None

    @pytest.mark.asyncio
    async def test_update_memory_refused(self, readonly_server):
        listed = await readonly_server.list_memories()
        memory_id = listed["memories"][0]["id"]
        result = await readonly_server.update_memory(
            memory_id=memory_id, title="should not change"
        )
        assert result["success"] is False
        assert result.get("readonly") is True

    @pytest.mark.asyncio
    async def test_bulk_create_refused(self, readonly_server):
        result = await readonly_server.bulk_create(
            memories=[{"title": "blocked", "content": "x"}]
        )
        assert result["success"] is False
        assert result.get("readonly") is True

    @pytest.mark.asyncio
    async def test_batch_delete_refused(self, readonly_server):
        listed = await readonly_server.list_memories()
        ids = [m["id"] for m in listed["memories"]]
        result = await readonly_server.batch_delete(memory_ids=ids)
        assert result["success"] is False
        assert result.get("readonly") is True
        for mid in ids:
            assert readonly_server.kernel.graph.get(mid) is not None

    @pytest.mark.asyncio
    async def test_search_still_works(self, readonly_server):
        result = await readonly_server.search_vault(query="first note", top_k=3)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_auto_hook_response_refused(self, readonly_server):
        result = await readonly_server.autonomous_hooks.auto_hook_response(
            user_query="What was the decision?",
            ai_response="It was X.",
            auto_save=True,
        )
        assert result["success"] is True
        assert result.get("saved") is False
        assert result.get("readonly") is True


class TestVaultLock:
    """Advisory PID lock must block a second writer on the same vault."""

    def test_lock_file_created_on_startup(self, mcp_server, temp_vault):
        lock_file = temp_vault / ".memograph.lock"
        assert lock_file.exists()
        import json

        payload = json.loads(lock_file.read_text(encoding="utf-8"))
        assert payload["role"] == "mcp-server"
        assert payload["pid"] > 0

    def test_lock_released_on_close(self, mcp_server, temp_vault):
        lock_file = temp_vault / ".memograph.lock"
        assert lock_file.exists()
        mcp_server.close()
        assert not lock_file.exists()

    def test_close_is_idempotent(self, mcp_server):
        mcp_server.close()
        mcp_server.close()  # must not raise

    def test_second_server_refused(self, mcp_server, temp_vault):
        # mcp_server already holds the lock for this temp_vault.
        with pytest.raises(RuntimeError, match="already in use"):
            MemoGraphMCPServer(vault_path=str(temp_vault))

    def test_readonly_server_skips_lock(self, temp_vault, monkeypatch):
        # First server: read-write, holds the lock.
        rw_server = MemoGraphMCPServer(vault_path=str(temp_vault))
        try:
            # Second server: read-only — must boot even though RW lock is held.
            monkeypatch.setenv("MEMOGRAPH_READONLY", "true")
            ro_server = MemoGraphMCPServer(vault_path=str(temp_vault))
            try:
                assert ro_server.readonly is True
                assert ro_server._vault_lock is None
            finally:
                ro_server.close()
        finally:
            rw_server.close()

    def test_stale_lock_is_reclaimed(self, temp_vault):
        # Pre-seed a lock file pointing at a PID that is almost certainly dead
        # (PID 1 belongs to init/systemd on POSIX and is not callable here;
        # on Windows it's reserved). We fake host="not-our-host" so the PID
        # liveness check is bypassed and the file is treated as foreign+stale.
        import json
        import socket

        lock_file = temp_vault / ".memograph.lock"
        lock_file.write_text(
            json.dumps(
                {
                    "pid": 999999,  # almost certainly not alive
                    "host": socket.gethostname(),  # same host so we hit the alive-check
                    "role": "mcp-server",
                    "started_at": "1970-01-01T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        server = MemoGraphMCPServer(vault_path=str(temp_vault))
        try:
            # Server booted because the stale lock was reclaimed; new lock
            # now belongs to us.
            payload = json.loads(lock_file.read_text(encoding="utf-8"))
            import os

            assert payload["pid"] == os.getpid()
        finally:
            server.close()

    def test_skip_lock_env_var(self, temp_vault, monkeypatch):
        monkeypatch.setenv("MEMOGRAPH_SKIP_LOCK", "true")
        server = MemoGraphMCPServer(vault_path=str(temp_vault))
        try:
            assert server._vault_lock is None
            assert not (temp_vault / ".memograph.lock").exists()
        finally:
            server.close()
