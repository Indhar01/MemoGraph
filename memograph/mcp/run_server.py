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
        elif name == "configure_autonomous_mode":
            result = await memograph_server.configure_autonomous_mode(**arguments)
        elif name == "get_autonomous_config":
            result = await memograph_server.get_autonomous_config()
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

    # Initialize MemoGraph server
    memograph_server = MemoGraphMCPServer(
        vault_path=vault_path,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )

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

        else:
            raise ValueError(f"Unknown prompt: {name}")

    # Run stdio server
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MemoGraph MCP Server started (stdio mode)")
        logger.info(f"Vault: {vault_path}")
        logger.info(f"Provider: {llm_provider}")
        logger.info("Ready for requests...")

        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Main entry point for MCP server."""
    parser = argparse.ArgumentParser(
        description="MemoGraph MCP Server - Expose vault to AI assistants"
    )
    parser.add_argument(
        "--vault",
        default=os.environ.get("MEMOGRAPH_VAULT", "~/my-vault"),
        help="Path to MemoGraph vault (default: $MEMOGRAPH_VAULT or ~/my-vault)",
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
