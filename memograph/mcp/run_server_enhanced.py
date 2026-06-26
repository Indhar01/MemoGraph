#!/usr/bin/env python3
"""Enhanced MCP server with context interception, deduplication, and debug logging.

This enhanced version adds:
1. Context parameter interception (captures conversation history Claude sends)
2. MD5 hash-based deduplication (prevents duplicate saves)
3. Non-blocking auto-save (uses asyncio.create_task)
4. Debug logging to vault/.memograph_debug.log
5. Optional chat_summary parameter in tool schemas
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    ResourceTemplate,
    TextContent,
    TextResourceContents,
    Tool,
)

from .server import MemoGraphMCPServer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Global MemoGraph server instance
memograph_server: MemoGraphMCPServer | None = None

# Conversation context tracking with deduplication
conversation_context: dict[str, Any] = {
    "last_user_query": None,
    "last_tool_call": None,
    "last_result": None,
    "auto_save_enabled": os.environ.get(
        "MEMOGRAPH_AUTO_SAVE_AFTER_QUERY", "false"
    ).lower()
    == "true",
    "saved_hashes": set(),  # Track saved content hashes for deduplication
}

# Debug logger
debug_logger: logging.Logger | None = None


def setup_debug_logging(vault_path: Path):
    """Setup debug logging to vault/.memograph_debug.log"""
    global debug_logger

    debug_log_path = vault_path / ".memograph_debug.log"

    # Create file handler
    file_handler = logging.FileHandler(debug_log_path, mode="a")
    file_handler.setLevel(logging.DEBUG)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)

    # Create debug logger
    debug_logger = logging.getLogger("memograph.debug")
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.addHandler(file_handler)

    debug_logger.info("=" * 80)
    debug_logger.info("MemoGraph MCP Server Started (Enhanced Mode)")
    debug_logger.info(f"Vault: {vault_path}")
    debug_logger.info(f"Auto-save enabled: {conversation_context['auto_save_enabled']}")
    debug_logger.info("=" * 80)


def compute_content_hash(content: str) -> str:
    """Compute MD5 hash of content for deduplication."""
    return hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()


def is_duplicate(content: str) -> bool:
    """Check if content has already been saved."""
    content_hash = compute_content_hash(content)

    if content_hash in conversation_context["saved_hashes"]:
        if debug_logger:
            debug_logger.debug(f"Duplicate detected: {content_hash[:8]}...")
        return True

    # Add to saved hashes
    conversation_context["saved_hashes"].add(content_hash)

    # Limit hash set size to prevent memory bloat (keep last 1000)
    if len(conversation_context["saved_hashes"]) > 1000:
        # Remove oldest (convert to list, remove first 100, convert back)
        hashes_list = list(conversation_context["saved_hashes"])
        conversation_context["saved_hashes"] = set(hashes_list[100:])

    return False


async def auto_save_context(
    context_data: str, tool_name: str, arguments: dict[str, Any]
) -> None:
    """
    Auto-save context in background (fire-and-forget pattern).

    This runs as a background task and won't block the main tool execution.
    """
    try:
        if debug_logger:
            debug_logger.info(f"🔍 Context intercepted from {tool_name}")
            debug_logger.debug(f"Context preview: {context_data[:200]}...")

        # Check for duplicates
        if is_duplicate(context_data):
            if debug_logger:
                debug_logger.info("⊘ Skipped: Duplicate content")
            return

        # Extract meaningful query from arguments
        query = (
            arguments.get("query")
            or arguments.get("question")
            or "Context from tool call"
        )

        # Save using autonomous hooks
        if memograph_server:
            result = await memograph_server.autonomous_hooks.auto_hook_response(
                user_query=query,
                ai_response=f"Context captured from {tool_name}:\n\n{context_data}",
                sources_used=[],
                conversation_id=None,
                auto_save=True,
            )

            if debug_logger:
                if result.get("saved"):
                    debug_logger.info(
                        f"✅ Context saved: {result.get('path', 'unknown')}"
                    )
                else:
                    debug_logger.warning(
                        f"⚠️ Context save failed: {result.get('error', 'unknown')}"
                    )

    except Exception as e:
        # Log error but don't crash
        if debug_logger:
            debug_logger.error(f"❌ Auto-save context error: {e}", exc_info=True)
        logger.error(f"Auto-save context error: {e}")


async def auto_save_result(query: str, result: dict[str, Any], tool_name: str) -> None:
    """
    Auto-save tool result in background (fire-and-forget pattern).

    This runs as a background task and won't block the main tool execution.
    """
    try:
        if debug_logger:
            debug_logger.info(f"💾 Auto-saving result from {tool_name}")

        # Format result for saving
        if tool_name == "search_vault":
            memories = result.get("memories", [])
            if not memories:
                if debug_logger:
                    debug_logger.info("⊘ Skipped: No memories found")
                return

            context = "\n\n".join(
                [
                    f"**{m.get('title', 'Untitled')}**\n{m.get('content', '')[:200]}..."
                    for m in memories[:3]
                ]
            )

            # Check for duplicates
            if is_duplicate(f"{query}:{context}"):
                if debug_logger:
                    debug_logger.info("⊘ Skipped: Duplicate search result")
                return

            sources = [
                {"id": m.get("id"), "title": m.get("title")} for m in memories[:5]
            ]

            ai_response = f"Found {len(memories)} relevant memories:\n\n{context}"

        elif tool_name == "query_with_context":
            context = result.get("context", "")
            sources = result.get("sources", [])

            if not context:
                if debug_logger:
                    debug_logger.info("⊘ Skipped: No context retrieved")
                return

            # Check for duplicates
            if is_duplicate(f"{query}:{context}"):
                if debug_logger:
                    debug_logger.info("⊘ Skipped: Duplicate query result")
                return

            ai_response = context

        else:
            if debug_logger:
                debug_logger.info(
                    f"⊘ Skipped: Tool {tool_name} not configured for auto-save"
                )
            return

        # Save using autonomous hooks
        if memograph_server:
            save_result = await memograph_server.autonomous_hooks.auto_hook_response(
                user_query=query,
                ai_response=ai_response,
                sources_used=sources,
                conversation_id=None,
                auto_save=True,
            )

            if debug_logger:
                if save_result.get("saved"):
                    debug_logger.info(
                        f"✅ Result saved: {save_result.get('path', 'unknown')}"
                    )
                else:
                    debug_logger.warning(
                        f"⚠️ Result save failed: {save_result.get('error', 'unknown')}"
                    )

    except Exception as e:
        # Log error but don't crash
        if debug_logger:
            debug_logger.error(f"❌ Auto-save result error: {e}", exc_info=True)
        logger.error(f"Auto-save result error: {e}")


async def handle_list_tools() -> list[Tool]:
    """List available tools with enhanced schemas."""
    if not memograph_server:
        return []

    schemas = memograph_server.get_tools_schema()

    # Enhance schemas with optional chat_summary parameter
    enhanced_schemas = []
    for schema in schemas:
        # Add chat_summary to all tools
        if "properties" not in schema["inputSchema"]:
            schema["inputSchema"]["properties"] = {}

        schema["inputSchema"]["properties"]["chat_summary"] = {
            "type": "string",
            "description": "Optional: Recent conversation context/summary to save alongside this operation",
        }

        enhanced_schemas.append(schema)

    # Convert to MCP Tool format
    tools = []
    for schema in enhanced_schemas:
        tool = Tool(
            name=schema["name"],
            description=schema["description"],
            inputSchema=schema["inputSchema"],
        )
        tools.append(tool)

    return tools


async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool execution with context interception and auto-save."""
    if not memograph_server:
        return [TextContent(type="text", text="Error: Server not initialized")]

    try:
        if debug_logger:
            debug_logger.info(f"🔧 Tool called: {name}")
            debug_logger.debug(f"Arguments: {json.dumps(arguments, indent=2)}")

        # ENHANCEMENT 1: Intercept chat_summary parameter BEFORE tool execution
        chat_summary = arguments.pop("chat_summary", None)
        if chat_summary and conversation_context["auto_save_enabled"]:
            if debug_logger:
                debug_logger.info("📝 Chat summary detected, saving in background...")

            # Fire-and-forget: Save context without blocking
            asyncio.create_task(auto_save_context(chat_summary, name, arguments))

        # Execute the actual tool
        if name == "search_vault":
            result = await memograph_server.search_vault(**arguments)
        elif name == "create_memory":
            result = await memograph_server.create_memory(**arguments)
        elif name == "query_with_context":
            result = await memograph_server.query_with_context(**arguments)
        elif name == "get_vault_info":
            result = await memograph_server.get_vault_info()
        elif name == "get_vault_stats":
            result = await memograph_server.get_vault_stats()
        elif name == "list_memories":
            result = await memograph_server.list_memories(**arguments)
        elif name == "get_memory":
            result = await memograph_server.get_memory(**arguments)
        elif name == "import_document":
            result = await memograph_server.import_document(**arguments)
        elif name == "delete_memory":
            result = await memograph_server.delete_memory(**arguments)
        elif name == "update_memory":
            result = await memograph_server.update_memory(**arguments)
        elif name == "list_available_tools":
            result = await memograph_server.list_available_tools()
        elif name == "auto_hook_query":
            result = await memograph_server.auto_hook_query(**arguments)
        elif name == "auto_hook_response":
            result = await memograph_server.auto_hook_response(**arguments)
        elif name == "auto_hook_turn":
            result = await memograph_server.auto_hook_turn(**arguments)
        elif name == "configure_autonomous_mode":
            result = await memograph_server.configure_autonomous_mode(**arguments)
        elif name == "configure_capture_mode":
            result = await memograph_server.configure_capture_mode(**arguments)
        elif name == "get_autonomous_config":
            result = await memograph_server.get_autonomous_config()
        elif name == "get_capture_mode":
            result = await memograph_server.get_capture_mode()
        elif name == "verify_last_save":
            result = await memograph_server.verify_last_save(**arguments)
        elif name == "get_save_stats":
            result = await memograph_server.get_save_stats(**arguments)
        elif name == "get_auto_save_analytics":
            result = await memograph_server.get_auto_save_analytics(**arguments)
        elif name == "get_monitor_status":
            result = await memograph_server.get_monitor_status()
        elif name == "relate_memories":
            result = await memograph_server.relate_memories(**arguments)
        elif name == "search_by_graph":
            result = await memograph_server.search_by_graph(**arguments)
        elif name == "find_path":
            result = await memograph_server.find_path(**arguments)
        elif name == "bulk_create":
            result = await memograph_server.bulk_create(**arguments)
        else:
            result = {
                "success": False,
                "error": f"Unknown tool: {name}",
            }

        # ENHANCEMENT 2: Auto-save result AFTER tool execution (non-blocking)
        if conversation_context["auto_save_enabled"] and result.get("success"):
            # Only auto-save for search/query tools
            if name in ["search_vault", "query_with_context"]:
                query = arguments.get("query") or arguments.get("question", "")

                # Only auto-save meaningful queries
                if query and len(query) >= 10:
                    if debug_logger:
                        debug_logger.info(f"💾 Triggering auto-save for {name}...")

                    # Fire-and-forget: Save result without blocking
                    asyncio.create_task(auto_save_result(query, result, name))

                    # Add metadata to result
                    result["auto_save_triggered"] = True

        # Format result as text content
        result_text = json.dumps(result, indent=2)
        return [TextContent(type="text", text=result_text)]

    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}")
        if debug_logger:
            debug_logger.error(f"❌ Tool execution error: {e}", exc_info=True)

        error_result = {
            "success": False,
            "error": str(e),
        }
        return [TextContent(type="text", text=json.dumps(error_result, indent=2))]


async def run_server(vault_path: str, llm_provider: str, llm_model: str | None):
    """Run the enhanced MCP server."""
    global memograph_server

    vault_path_obj = Path(vault_path).expanduser().resolve()

    # Setup debug logging
    setup_debug_logging(vault_path_obj)

    if debug_logger:
        debug_logger.info("🚀 Starting enhanced MCP server...")

    try:
        from .card_server import start_card_server

        card_port = int(os.environ.get("CARD_SERVER_PORT", "8080"))
        start_card_server(port=card_port)
        logger.info(f"Card server started on port {card_port}")
        if debug_logger:
            debug_logger.info(f"📡 Card server: http://localhost:{card_port}")
    except Exception as e:
        logger.warning(f"Card server failed to start (non-fatal): {e}")
        if debug_logger:
            debug_logger.warning(f"⚠️ Card server failed: {e}")

    # Initialize MemoGraph server
    try:
        # Validate path
        if vault_path_obj.exists() and not vault_path_obj.is_dir():
            logger.error(f"❌ Vault path is a file, not a directory: {vault_path}")
            sys.exit(1)

        # Test write permissions
        if vault_path_obj.exists():
            test_file = vault_path_obj / ".memograph_write_test"
            try:
                test_file.touch()
                test_file.unlink()
            except PermissionError:
                logger.error(f"❌ No write permission for vault: {vault_path}")
                sys.exit(1)

        memograph_server = MemoGraphMCPServer(
            vault_path=str(vault_path_obj),
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        logger.info("✓ MemoGraph server initialized successfully")
        if debug_logger:
            debug_logger.info("✅ Server initialized")

        # Start monitor
        memograph_server.start_monitor()
        if debug_logger:
            debug_logger.info("👁️ Conversation monitor started")

    except Exception as e:
        logger.error(f"❌ Server initialization failed: {e}", exc_info=True)
        if debug_logger:
            debug_logger.error(f"❌ Initialization failed: {e}", exc_info=True)
        sys.exit(1)

    logger.info(f"Initialized MemoGraph MCP server with vault: {vault_path}")

    # Create MCP server
    server = Server("memograph-enhanced")

    # Register tool handlers
    @server.list_tools()
    async def list_tools_handler():
        return await handle_list_tools()

    @server.call_tool()
    async def call_tool_handler(name: str, arguments: dict):
        return await handle_call_tool(name, arguments)

    # Register resource handlers (same as original)
    @server.list_resources()
    async def list_resources_handler():
        if not memograph_server:
            return []
        nodes = memograph_server.kernel.graph.all_nodes()
        from typing import cast
        from mcp.types import AnyUrl

        return [
            Resource(
                uri=cast(AnyUrl, f"memograph://vault/{node.id}"),
                name=node.title,
                description=f"[{node.memory_type.value}] {', '.join(node.tags)}"
                if node.tags
                else f"[{node.memory_type.value}]",
                mimeType="text/markdown",
            )
            for node in nodes
        ]

    @server.read_resource()
    async def read_resource_handler(uri: str):
        if not memograph_server:
            raise ValueError("Server not initialized")

        uri_str = str(uri)
        if uri_str.startswith("memograph://vault/"):
            memory_id = uri_str.replace("memograph://vault/", "")
            node = memograph_server.kernel.graph.get(memory_id)
            if not node:
                raise ValueError(f"Memory not found: {memory_id}")

            content = f"# {node.title}\n\n"
            content += f"**Type:** {node.memory_type.value} | "
            content += f"**Salience:** {node.salience} | "
            content += f"**Tags:** {', '.join(node.tags)}\n\n"
            if node.links:
                content += f"**Links:** {', '.join(node.links)}\n\n"
            content += node.content

            from typing import cast
            from mcp.types import AnyUrl

            return [
                TextResourceContents(
                    uri=cast(AnyUrl, uri_str), text=content, mimeType="text/markdown"
                )
            ]

        elif uri_str.startswith("memograph://tag/"):
            tag = uri_str.replace("memograph://tag/", "")
            nodes = memograph_server.kernel.graph.get_by_tag(tag)
            content = f"# Memories tagged: {tag}\n\n"
            for node in nodes:
                content += f"- **{node.title}** ({node.memory_type.value}, salience: {node.salience})\n"
            from typing import cast
            from mcp.types import AnyUrl

            return [
                TextResourceContents(
                    uri=cast(AnyUrl, uri_str), text=content, mimeType="text/markdown"
                )
            ]

        else:
            raise ValueError(f"Unknown URI scheme: {uri_str}")

    @server.list_resource_templates()
    async def list_resource_templates_handler():
        return [
            ResourceTemplate(
                uriTemplate="memograph://vault/{memory_id}",
                name="Memory by ID",
                description="Get a specific memory by its ID",
                mimeType="text/markdown",
            ),
            ResourceTemplate(
                uriTemplate="memograph://tag/{tag}",
                name="Memories by tag",
                description="List all memories with a specific tag",
            ),
        ]

    # Register prompt handlers (same as original - omitted for brevity)
    @server.list_prompts()
    async def list_prompts_handler():
        return []  # Simplified for this enhanced version

    @server.get_prompt()
    async def get_prompt_handler(name: str, arguments: dict | None = None):
        raise ValueError("Prompts not implemented in enhanced version")

    # Run stdio server
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MemoGraph Enhanced MCP Server started (stdio mode)")
        logger.info(f"Vault: {vault_path}")
        logger.info(f"Provider: {llm_provider}")
        logger.info(f"Debug log: {vault_path_obj}/.memograph_debug.log")
        logger.info("Ready for requests...")

        if debug_logger:
            debug_logger.info("🎯 Server ready for requests")

        try:
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        finally:
            # Clean up
            if memograph_server:
                await memograph_server.stop_monitor()
            if debug_logger:
                debug_logger.info("🛑 Server stopped")


def main():
    """Main entry point for enhanced MCP server."""
    parser = argparse.ArgumentParser(
        description="MemoGraph Enhanced MCP Server - With context interception and deduplication"
    )
    parser.add_argument(
        "--vault",
        default=os.environ.get("MEMOGRAPH_VAULT", "~/my-vault"),
        help="Path to MemoGraph vault",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("MEMOGRAPH_PROVIDER"),
        choices=["ollama", "claude"],
        help="LLM provider",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("MEMOGRAPH_MODEL"),
        help="LLM model name",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Validate vault path
    vault_path = Path(args.vault).expanduser()
    if not vault_path.exists():
        logger.warning(f"Vault path does not exist, will be created: {vault_path}")
        vault_path.mkdir(parents=True, exist_ok=True)

    # Run server
    try:
        asyncio.run(
            run_server(
                vault_path=str(vault_path),
                llm_provider=args.provider,
                llm_model=args.model,
            )
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
