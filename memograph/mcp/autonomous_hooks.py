"""Autonomous hooks for MemoGraph MCP Server.

This module provides autonomous behavior for the MCP server, allowing it to
automatically search the vault and save interactions without explicit user commands.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from ..core.enums import MemoryType

logger = logging.getLogger(__name__)


class AutonomousHooks:
    """Autonomous hooks for automatic vault interaction.

    This class provides hooks that can be called automatically during
    user interactions to search the vault and save conversations.
    """

    def __init__(self, server):
        """Initialize autonomous hooks.

        Args:
            server: Reference to the MemoGraphMCPServer instance
        """
        self.server = server
        self.kernel = server.kernel

        # Configuration
        self.auto_search_enabled = False
        self.auto_save_queries = False
        self.auto_save_responses = True
        self.min_query_length = 10

        logger.info("Autonomous hooks initialized")

    async def auto_hook_query(
        self,
        user_query: str,
        conversation_id: str | None = None,
        auto_search: bool | None = None,
        auto_save_query: bool | None = None,
    ) -> dict[str, Any]:
        """Autonomous hook for every user query.

        Automatically searches vault and optionally saves the query.

        Args:
            user_query: The user's query/question
            conversation_id: Optional conversation ID for tracking
            auto_search: Override auto_search setting
            auto_save_query: Override auto_save_queries setting

        Returns:
            Dictionary with context, sources, and actions performed
        """
        try:
            # Check if query is long enough
            if len(user_query.strip()) < self.min_query_length:
                return {
                    "success": True,
                    "message": "Query too short for autonomous processing",
                    "context": None,
                    "sources": [],
                    "actions": [],
                }

            actions = []
            context = None
            sources = []

            # Determine if we should search
            should_search = (
                auto_search if auto_search is not None else self.auto_search_enabled
            )

            if should_search:
                # Search vault for relevant context with timeout
                try:
                    import asyncio
                    from ..core.assistant import retrieve_cited_context

                    # Run search with 10 second timeout to prevent hanging
                    try:
                        context, source_list = await asyncio.wait_for(
                            asyncio.to_thread(
                                retrieve_cited_context,
                                kernel=self.kernel,
                                query=user_query,
                                tags=None,
                                top_k=5,
                            ),
                            timeout=10.0,
                        )

                        sources = [
                            {
                                "id": src.source_id,
                                "title": src.title,
                                "memory_type": src.memory_type,
                                "tags": src.tags,
                            }
                            for src in source_list
                        ]

                        actions.append("searched_vault")
                        logger.info(
                            f"Auto-searched vault for query, found {len(sources)} sources"
                        )

                    except asyncio.TimeoutError:
                        logger.warning("Auto-search timed out after 10 seconds")
                        # Continue without context instead of failing completely

                except Exception as e:
                    logger.warning(f"Auto-search failed: {e}")

            # Determine if we should save query
            should_save = (
                auto_save_query
                if auto_save_query is not None
                else self.auto_save_queries
            )

            if should_save:
                # Save the query as a memory
                try:
                    title = f"Query: {user_query[:50]}..."
                    content = f"**User Query**\n\n{user_query}"

                    if conversation_id:
                        content += f"\n\n**Conversation ID**: {conversation_id}"

                    self.kernel.remember(
                        title=title,
                        content=content,
                        memory_type=MemoryType.EPISODIC,
                        tags=["query", "conversation"],
                        salience=0.5,
                    )

                    actions.append("saved_query")
                    logger.info("Auto-saved user query")

                except Exception as e:
                    logger.warning(f"Auto-save query failed: {e}")

            return {
                "success": True,
                "context": context,
                "sources": sources,
                "actions": actions,
                "message": f"Autonomous processing complete: {', '.join(actions) if actions else 'no actions taken'}",
            }

        except Exception as e:
            logger.error(f"Error in auto_hook_query: {e}")
            return {
                "success": False,
                "error": str(e),
                "context": None,
                "sources": [],
                "actions": [],
            }

    async def auto_hook_response(
        self,
        user_query: str,
        ai_response: str,
        sources_used: list[dict[str, Any]] | None = None,
        conversation_id: str | None = None,
        auto_save: bool | None = None,
    ) -> dict[str, Any]:
        """Autonomous hook after AI responds.

        Saves the complete interaction as a memory.

        Args:
            user_query: Original user query
            ai_response: AI's response
            sources_used: List of source memories that were used
            conversation_id: Optional conversation ID
            auto_save: Override auto_save_responses setting

        Returns:
            Dictionary with save result
        """
        try:
            # Determine if we should save
            should_save = (
                auto_save if auto_save is not None else self.auto_save_responses
            )

            if not should_save:
                return {
                    "success": True,
                    "message": "Auto-save disabled",
                    "saved": False,
                }

            # Create memory title
            title = f"Conversation: {user_query[:50]}..."

            # Build content
            content = f"**User Query**\n\n{user_query}\n\n"
            content += f"**AI Response**\n\n{ai_response}\n\n"

            if sources_used:
                content += "**Sources Used**\n\n"
                for source in sources_used:
                    content += f"- [[{source.get('id', 'unknown')}]] {source.get('title', 'Untitled')}\n"
                content += "\n"

            if conversation_id:
                content += f"**Conversation ID**: {conversation_id}\n"

            content += f"\n**Timestamp**: {datetime.now(timezone.utc).isoformat()}"

            # Save as episodic memory
            path = self.kernel.remember(
                title=title,
                content=content,
                memory_type=MemoryType.EPISODIC,
                tags=["conversation", "interaction"],
                salience=0.7,
            )

            logger.info(f"Auto-saved conversation to: {path}")

            return {
                "success": True,
                "message": "Conversation saved successfully",
                "saved": True,
                "path": path,
            }

        except Exception as e:
            logger.error(f"Error in auto_hook_response: {e}")
            return {
                "success": False,
                "error": str(e),
                "saved": False,
            }

    async def configure(
        self,
        auto_search: bool | None = None,
        auto_save_queries: bool | None = None,
        auto_save_responses: bool | None = None,
        min_query_length: int | None = None,
    ) -> dict[str, Any]:
        """Configure autonomous hooks settings.

        Args:
            auto_search: Enable/disable auto-search
            auto_save_queries: Enable/disable saving queries
            auto_save_responses: Enable/disable saving responses
            min_query_length: Minimum query length to process

        Returns:
            Dictionary with updated configuration
        """
        try:
            if auto_search is not None:
                self.auto_search_enabled = auto_search

            if auto_save_queries is not None:
                self.auto_save_queries = auto_save_queries

            if auto_save_responses is not None:
                self.auto_save_responses = auto_save_responses

            if min_query_length is not None:
                if min_query_length < 1:
                    return {
                        "success": False,
                        "error": "min_query_length must be at least 1",
                    }
                self.min_query_length = min_query_length

            logger.info("Autonomous hooks configuration updated")

            return {
                "success": True,
                "message": "Configuration updated successfully",
                "configuration": self.get_configuration(),
            }

        except Exception as e:
            logger.error(f"Error configuring autonomous hooks: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_configuration(self) -> dict[str, Any]:
        """Get current autonomous hooks configuration.

        Returns:
            Dictionary with current settings and recommendations
        """
        return {
            "auto_search_enabled": self.auto_search_enabled,
            "auto_save_queries": self.auto_save_queries,
            "auto_save_responses": self.auto_save_responses,
            "min_query_length": self.min_query_length,
            "recommendations": {
                "auto_search": "Enable to automatically provide context from vault for every query",
                "auto_save_queries": "Usually disabled to avoid noise; enable if you want to track all questions",
                "auto_save_responses": "Recommended: enabled to build conversation history",
                "min_query_length": "Set to 10-20 to filter out short queries like 'ok', 'thanks'",
            },
        }
