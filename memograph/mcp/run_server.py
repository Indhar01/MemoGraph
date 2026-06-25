#!/usr/bin/env python3
"""Run the MemoGraph MCP server using the official MCP SDK.

This script starts the MCP server that exposes MemoGraph functionality
to MCP-compatible AI clients like Claude Desktop, Cline, etc.

Usage:
    python -m memograph.mcp.run_server --vault ~/my-vault

    Or set environment variable:
    export MEMOGRAPH_VAULT=~/my-vault
    python -m memograph.mcp.run_server
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
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

# Conversation context tracking for auto-save
conversation_context: dict[str, Any] = {
    "last_user_query": None,
    "last_tool_call": None,
    "last_result": None,
    "auto_save_enabled": os.environ.get(
        "MEMOGRAPH_AUTO_SAVE_AFTER_QUERY", "false"
    ).lower()
    == "true",
}


async def handle_list_tools() -> list[Tool]:
    """List available tools."""
    if not memograph_server:
        return []

    schemas = memograph_server.get_tools_schema()

    # Convert our schema format to MCP Tool format
    tools = []
    for schema in schemas:
        tool = Tool(
            name=schema["name"],
            description=schema["description"],
            inputSchema=schema["inputSchema"],
        )
        tools.append(tool)

    return tools


async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool execution."""
    if not memograph_server:
        return [TextContent(type="text", text="Error: Server not initialized")]

    try:
        # Route to appropriate handler
        if name == "search_vault":
            result = await memograph_server.search_vault(**arguments)

            # Auto-save conversation if enabled and search was successful
            if conversation_context["auto_save_enabled"] and result.get("success"):
                try:
                    query = arguments.get("query", "")
                    memories = result.get("memories", [])

                    # Only auto-save if we have meaningful search
                    if query and len(query) >= 10 and memories:
                        logger.info("🤖 Auto-saving conversation after search_vault")

                        # Format memories as context
                        context = "\n\n".join(
                            [
                                f"**{m.get('title', 'Untitled')}**\n{m.get('content', '')[:200]}..."
                                for m in memories[:3]
                            ]
                        )

                        sources = [
                            {"id": m.get("id"), "title": m.get("title")}
                            for m in memories[:5]
                        ]

                        # Trigger auto_hook_response automatically
                        auto_save_result = await memograph_server.autonomous_hooks.auto_hook_response(
                            user_query=query,
                            ai_response=f"Found {len(memories)} relevant memories:\n\n{context}",
                            sources_used=sources,
                            conversation_id=None,
                            auto_save=True,
                        )

                        result["auto_saved"] = auto_save_result.get("saved", False)
                        result["auto_save_message"] = auto_save_result.get(
                            "message", ""
                        )

                        if auto_save_result.get("saved"):
                            logger.info("✅ Auto-save successful")

                except Exception as e:
                    logger.error(f"❌ Auto-save error: {e}")
                    result["auto_save_error"] = str(e)

        elif name == "create_memory":
            result = await memograph_server.create_memory(**arguments)
        elif name == "query_with_context":
            result = await memograph_server.query_with_context(**arguments)

            # Auto-save conversation if enabled
            if conversation_context["auto_save_enabled"] and result.get("success"):
                try:
                    question = arguments.get("question", "")
                    context = result.get("context", "")
                    sources = result.get("sources", [])

                    # Only auto-save if we have meaningful content
                    if question and len(question) >= 10:
                        logger.info(
                            "🤖 Auto-saving conversation after query_with_context"
                        )

                        # Trigger auto_hook_response automatically
                        auto_save_result = (
                            await memograph_server.autonomous_hooks.auto_hook_response(
                                user_query=question,
                                ai_response=context
                                if context
                                else "Context retrieved from vault",
                                sources_used=sources,
                                conversation_id=None,
                                auto_save=True,
                            )
                        )

                        # Add auto-save info to result
                        result["auto_saved"] = auto_save_result.get("saved", False)
                        result["auto_save_message"] = auto_save_result.get(
                            "message", ""
                        )

                        if auto_save_result.get("saved"):
                            logger.info(
                                f"✅ Auto-save successful: {auto_save_result.get('path', 'unknown')}"
                            )
                        else:
                            logger.warning(
                                f"⚠️ Auto-save failed: {auto_save_result.get('error', 'unknown')}"
                            )

                except Exception as e:
                    logger.error(f"❌ Auto-save error: {e}")
                    # Don't fail the original query if auto-save fails
                    result["auto_save_error"] = str(e)
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
        elif name == "configure_autonomous_mode":
            result = await memograph_server.configure_autonomous_mode(**arguments)
        elif name == "get_autonomous_config":
            result = await memograph_server.get_autonomous_config()
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

        # Format result as text content
        import json

        result_text = json.dumps(result, indent=2)
        return [TextContent(type="text", text=result_text)]

    except ImportError as e:
        # An optional extra is missing — surface a structured payload with an
        # install hint so the client can show it to the user instead of a
        # bare ModuleNotFoundError.
        logger.error(f"Tool {name} hit a missing optional dependency: {e}")
        import json

        error_result = {
            "success": False,
            "error": str(e),
            "missing_dependency": True,
            "hint": (
                "This tool needs an optional extra. Install one of: "
                "pip install 'memograph[embeddings]'   # local embeddings\n"
                "pip install 'memograph[anthropic]'    # Claude provider\n"
                "pip install 'memograph[openai]'       # OpenAI embeddings/LLM\n"
                "pip install 'memograph[ollama]'       # Ollama local LLM\n"
                "pip install 'memograph[all]'          # everything"
            ),
        }
        return [TextContent(type="text", text=json.dumps(error_result, indent=2))]

    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}")
        import json

        error_result = {
            "success": False,
            "error": str(e),
        }
        return [TextContent(type="text", text=json.dumps(error_result, indent=2))]


async def run_server(vault_path: str, llm_provider: str, llm_model: str | None):
    """Run the MCP server using the official SDK."""
    global memograph_server

    try:
        from .card_server import start_card_server

        card_port = int(os.environ.get("CARD_SERVER_PORT", "8080"))
        start_card_server(port=card_port)
        logger.info(f"Card server started on port {card_port}")
    except Exception as e:
        logger.warning(f"Card server failed to start (non-fatal): {e}")

    # Initialize MemoGraph server with comprehensive error handling
    try:
        vault_path_obj = Path(vault_path).expanduser().resolve()

        # Validate path is directory, not file
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

        # Start monitor after server is fully initialized (must be in async context)
        memograph_server.start_monitor()

    except PermissionError as e:
        logger.error(f"❌ Permission denied: {vault_path} - {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Server initialization failed: {e}", exc_info=True)
        sys.exit(1)

    logger.info(f"Initialized MemoGraph MCP server with vault: {vault_path}")

    # Create MCP server
    server = Server("memograph")

    # Register tool handlers
    @server.list_tools()
    async def list_tools_handler():
        return await handle_list_tools()

    @server.call_tool()
    async def call_tool_handler(name: str, arguments: dict):
        return await handle_call_tool(name, arguments)

    # Register resource handlers
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

        # Parse URI: memograph://vault/{id} or memograph://tag/{tag}
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

    # Register prompt handlers
    @server.list_prompts()
    async def list_prompts_handler():
        return [
            Prompt(
                name="vault-summary",
                description="Get a summary of your entire memory vault",
            ),
            Prompt(
                name="recall",
                description="Recall what you know about a specific topic",
                arguments=[
                    PromptArgument(
                        name="topic", description="Topic to recall", required=True
                    )
                ],
            ),
            Prompt(
                name="weekly-review",
                description="Review recent memories for a weekly review",
            ),
            Prompt(
                name="find-connections",
                description="Find connections between two topics in your vault",
                arguments=[
                    PromptArgument(
                        name="topic_a", description="First topic", required=True
                    ),
                    PromptArgument(
                        name="topic_b", description="Second topic", required=True
                    ),
                ],
            ),
            Prompt(
                name="save-conversation",
                description="Save a specific conversation exchange to your memory vault",
                arguments=[
                    PromptArgument(
                        name="user_question",
                        description="The user's question or message",
                        required=True,
                    ),
                    PromptArgument(
                        name="assistant_response",
                        description="Your (the assistant's) response",
                        required=True,
                    ),
                ],
            ),
            Prompt(
                name="save-this-conversation",
                description="Save our current conversation to the vault (simplified - auto-extracts last exchange)",
            ),
            Prompt(
                name="conversation-history",
                description="Review recent conversation memories saved in the vault",
                arguments=[
                    PromptArgument(
                        name="limit",
                        description="Number of conversations to show (default: 10)",
                        required=False,
                    ),
                ],
            ),
        ]

    @server.get_prompt()
    async def get_prompt_handler(name: str, arguments: dict | None = None):
        if not memograph_server:
            raise ValueError("Server not initialized")

        arguments = arguments or {}

        if name == "vault-summary":
            stats = memograph_server.kernel.ingest(force=False)
            all_tags = memograph_server.kernel.graph.get_all_tags()
            type_counts = memograph_server.kernel.graph.get_type_counts()
            types_str = ", ".join(f"{k}: {v}" for k, v in type_counts.items())

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=(
                                f"Summarize my memory vault.\n\n"
                                f"**Stats:** {stats['total']} memories\n"
                                f"**Types:** {types_str}\n"
                                f"**Tags ({len(all_tags)}):** {', '.join(all_tags[:30])}\n\n"
                                f"Give me a high-level overview of what's in my vault, "
                                f"identify main themes, and suggest areas that could use more notes."
                            ),
                        ),
                    )
                ]
            )

        elif name == "recall":
            topic = arguments.get("topic", "")
            if not topic:
                raise ValueError("Topic is required for recall prompt")
            context = memograph_server.kernel.context_window(
                query=topic, top_k=10, token_limit=4096
            )
            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=(
                                f"What do I know about '{topic}'?\n\n"
                                f"Here is relevant context from my memory vault:\n\n{context}\n\n"
                                f"Synthesize this information and tell me what I know about '{topic}'. "
                                f"Highlight key facts, decisions, and any connections between ideas."
                            ),
                        ),
                    )
                ]
            )

        elif name == "weekly-review":
            nodes = memograph_server.kernel.graph.all_nodes()
            nodes.sort(key=lambda n: n.created_at or "", reverse=True)
            recent = nodes[:20]

            memories_text = ""
            for node in recent:
                date = node.created_at.strftime("%Y-%m-%d") if node.created_at else "?"
                memories_text += f"- [{date}] **{node.title}** ({node.memory_type.value}): {node.content[:100]}...\n"

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=(
                                f"Help me do a weekly review of my recent memories.\n\n"
                                f"**Recent memories ({len(recent)}):**\n{memories_text}\n"
                                f"Summarize what happened this week, highlight key decisions "
                                f"and action items, and suggest what I should follow up on."
                            ),
                        ),
                    )
                ]
            )

        elif name == "find-connections":
            topic_a = arguments.get("topic_a", "")
            topic_b = arguments.get("topic_b", "")
            if not topic_a or not topic_b:
                raise ValueError("Both topic_a and topic_b are required")

            context_a = memograph_server.kernel.context_window(
                query=topic_a, top_k=5, token_limit=2048
            )
            context_b = memograph_server.kernel.context_window(
                query=topic_b, top_k=5, token_limit=2048
            )

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=(
                                f"Find connections between '{topic_a}' and '{topic_b}' "
                                f"in my memory vault.\n\n"
                                f"**Context for '{topic_a}':**\n{context_a}\n\n"
                                f"**Context for '{topic_b}':**\n{context_b}\n\n"
                                f"Identify shared themes, common tags, related ideas, "
                                f"and suggest how these topics connect."
                            ),
                        ),
                    )
                ]
            )

        elif name == "save-conversation":
            user_question = arguments.get("user_question", "")
            assistant_response = arguments.get("assistant_response", "")

            if not user_question or not assistant_response:
                raise ValueError(
                    "Both user_question and assistant_response are required"
                )

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=(
                                f"Save this conversation to my vault using the auto_hook_response tool:\n\n"
                                f"User: {user_question}\n\n"
                                f"Assistant: {assistant_response}\n\n"
                                f"Call auto_hook_response with these as parameters."
                            ),
                        ),
                    )
                ]
            )

        elif name == "save-this-conversation":
            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=(
                                "Please save our most recent conversation exchange to my memory vault.\n\n"
                                "Use the auto_hook_response tool with:\n"
                                "- user_query: my last question to you\n"
                                "- ai_response: your complete answer\n\n"
                                "This builds our conversation history for future reference."
                            ),
                        ),
                    )
                ]
            )

        elif name == "conversation-history":
            limit = int(arguments.get("limit", 10))

            # List recent conversation memories
            nodes = memograph_server.kernel.graph.get_by_tags(
                ["conversation", "interaction"],
                match_all=False,
            )
            nodes.sort(key=lambda n: n.created_at or "", reverse=True)
            recent = nodes[:limit]

            if not recent:
                content = "No conversation memories found in vault.\n\nTip: Use auto_hook_response after conversations to save them."
            else:
                content = f"# Recent Conversation History ({len(recent)} memories)\n\n"
                for i, node in enumerate(recent, 1):
                    date = (
                        node.created_at.strftime("%Y-%m-%d %H:%M")
                        if node.created_at
                        else "Unknown date"
                    )
                    preview = (
                        node.content[:200] + "..."
                        if len(node.content) > 200
                        else node.content
                    )
                    content += f"## {i}. {node.title}\n"
                    content += f"**Saved**: {date}\n\n"
                    content += f"{preview}\n\n"
                    content += "---\n\n"

            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=content,
                        ),
                    )
                ]
            )

        else:
            raise ValueError(f"Unknown prompt: {name}")

    # Run stdio server
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MemoGraph MCP Server started (stdio mode)")
        logger.info(f"Vault: {vault_path}")
        logger.info(f"Provider: {llm_provider}")
        logger.info("Ready for requests...")

        try:
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        finally:
            # Clean up monitor and release the advisory vault lock on shutdown.
            if memograph_server:
                await memograph_server.stop_monitor()
                memograph_server.close()


def _resolve_vault_default() -> str:
    """Resolve the default vault path with optional multi-tenant resolution.

    Precedence:
      1. ``MEMOGRAPH_GLOBAL_ROOT`` + ``MEMOGRAPH_DEFAULT_TENANT_ID``
         -> ``<global_root>/<tenant_id>/`` (Phase 3.5: stdio MCP runs as
         a single configured tenant against the per-tenant directory
         layout).
      2. ``MEMOGRAPH_VAULT`` -> single-tenant path.
      3. ``~/my-vault`` -> back-compat default.

    Per-request token-derived tenant_id for HTTP/SSE MCP transport is
    a Phase 3.5.b follow-up; stdio mode is single-tenant by design.
    """
    global_root = os.environ.get("MEMOGRAPH_GLOBAL_ROOT")
    if global_root:
        tid = os.environ.get("MEMOGRAPH_DEFAULT_TENANT_ID", "default").strip()
        if tid:
            return str(Path(global_root).expanduser() / tid)
    return os.environ.get("MEMOGRAPH_VAULT", "~/my-vault")


def main():
    """Main entry point for MCP server."""
    parser = argparse.ArgumentParser(
        description="MemoGraph MCP Server - Expose vault to AI assistants"
    )
    parser.add_argument(
        "--vault",
        default=_resolve_vault_default(),
        help=(
            "Path to MemoGraph vault. Defaults to "
            "$MEMOGRAPH_GLOBAL_ROOT/$MEMOGRAPH_DEFAULT_TENANT_ID when both "
            "are set (multi-tenant), $MEMOGRAPH_VAULT otherwise, or "
            "~/my-vault as a final fallback."
        ),
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("MEMOGRAPH_PROVIDER"),
        choices=["ollama", "claude"],
        help="LLM provider for query_with_context (optional, only needed for AI-generated answers)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("MEMOGRAPH_MODEL"),
        help="LLM model name (default: provider default)",
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
