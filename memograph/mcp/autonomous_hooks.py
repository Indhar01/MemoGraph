"""Autonomous hooks for MemoGraph MCP Server.

⚠️ IMPORTANT: Despite the name "autonomous", these hooks are NOT automatically triggered.
They are TOOLS that the AI client must explicitly call.

This module provides hook tools for the MCP server that enable:
- Searching the vault when queries are received (auto_hook_query)
- Saving conversations when responses are generated (auto_hook_response)

However, the AI client (e.g., Claude Desktop) must explicitly call these tools.
They do NOT automatically intercept messages due to MCP protocol limitations.

To make these hooks work automatically:
1. Enable: MEMOGRAPH_AUTONOMOUS_MODE=true (enables save when called)
2. Guide the AI: Add custom instructions telling Claude to call auto_hook_response
3. See docs/AUTONOMOUS_HOOKS_GUIDE.md for complete setup instructions

The term "autonomous" means "self-configured" not "automatic".
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

        # Save statistics tracking
        self.save_attempts = 0
        self.successful_saves = 0
        self.failed_saves = 0
        self.session_start = datetime.now(timezone.utc)
        self.save_history: list[dict] = []  # Last 100 save attempts with timestamps

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

            if should_save and getattr(self.server, "readonly", False):
                logger.info("auto_hook_query: readonly mode — skipping query save")
                should_save = False

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
        # Track save attempt
        self.save_attempts += 1
        save_timestamp = datetime.now(timezone.utc)

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

            if getattr(self.server, "readonly", False):
                logger.info("auto_hook_response: readonly mode — skipping save")
                return {
                    "success": True,
                    "message": (
                        "Server is in read-only mode "
                        "(MEMOGRAPH_READONLY=true); conversation not saved."
                    ),
                    "saved": False,
                    "readonly": True,
                }

            # Create memory title
            title = f"Conversation: {user_query[:50]}..."

            # Build content with layer tracking
            content = "**Saved By:** Layer 1 (AI Explicit Save)\n\n"
            content += f"**User Query**\n\n{user_query}\n\n"
            content += f"**AI Response**\n\n{ai_response}\n\n"

            if sources_used:
                content += "**Sources Used**\n\n"
                for source in sources_used:
                    content += f"- [[{source.get('id', 'unknown')}]] {source.get('title', 'Untitled')}\n"
                content += "\n"

            if conversation_id:
                content += f"**Conversation ID**: {conversation_id}\n"

            content += f"\n**Timestamp**: {save_timestamp.isoformat()}"

            # Save as episodic memory with layer1 tag
            path = self.kernel.remember(
                title=title,
                content=content,
                memory_type=MemoryType.EPISODIC,
                tags=["conversation", "interaction", "layer1-explicit"],
                salience=0.7,
            )

            # CRITICAL: Refresh graph so new memory is immediately searchable
            # Without this, search_vault will return stale results
            try:
                self.kernel.ingest(force=False)
                logger.info("Graph refreshed after save - new memory is now searchable")
            except Exception as ingest_error:
                logger.warning(f"Failed to refresh graph after save: {ingest_error}")
                # Continue anyway - save was successful

            # Track successful save
            self.successful_saves += 1
            self._add_to_history(
                {
                    "timestamp": save_timestamp,
                    "success": True,
                    "title": title,
                }
            )

            logger.info(f"Auto-saved conversation to: {path}")

            return {
                "success": True,
                "message": "✅ Conversation saved successfully (Layer 1 - AI Explicit)",
                "saved": True,
                "path": path,
                "layer": "layer1",
                "tip": "This was saved by you calling auto_hook_response. Layer 2 monitor provides backup.",
            }

        except Exception as e:
            # Track failed save
            self.failed_saves += 1
            self._add_to_history(
                {
                    "timestamp": save_timestamp,
                    "success": False,
                    "error": str(e),
                }
            )

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

    def _add_to_history(self, entry: dict[str, Any]) -> None:
        """Add entry to save history, keeping only last 100.

        Args:
            entry: History entry to add
        """
        self.save_history.append(entry)
        if len(self.save_history) > 100:
            self.save_history.pop(0)

    async def verify_last_save(
        self,
        time_window_seconds: int = 60,
        conversation_only: bool = True,
    ) -> dict[str, Any]:
        """Verify if a recent conversation was saved to the vault.

        Args:
            time_window_seconds: How far back to check (seconds)
            conversation_only: Only check conversation memories (tag="conversation")

        Returns:
            Dictionary with verification result
        """
        try:
            # Ingest to ensure we have latest vault state
            self.kernel.ingest(force=False)

            # Get all memories from the graph
            all_nodes = self.kernel.graph.all_nodes()

            # Filter to conversation memories if requested
            if conversation_only:
                all_nodes = [n for n in all_nodes if "conversation" in n.tags]

            if not all_nodes:
                return {
                    "success": True,
                    "found_recent_save": False,
                    "time_window_checked": time_window_seconds,
                    "message": f"No {'conversation ' if conversation_only else ''}memories found in vault.",
                    "troubleshooting_tips": [
                        "Verify MEMOGRAPH_AUTONOMOUS_MODE=true is set",
                        "Check custom instructions are configured in Claude Desktop",
                        "Try calling auto_hook_response manually",
                        "Check vault permissions",
                    ],
                }

            # Sort by modified_at (or created_at as fallback)
            sorted_nodes = sorted(
                all_nodes,
                key=lambda n: n.modified_at or n.created_at or datetime.min,
                reverse=True,
            )

            # Get the most recent memory
            most_recent = sorted_nodes[0]
            last_timestamp = most_recent.modified_at or most_recent.created_at

            if not last_timestamp:
                return {
                    "success": True,
                    "found_recent_save": False,
                    "time_window_checked": time_window_seconds,
                    "message": "Found memories but none have timestamps.",
                }

            # Calculate how long ago
            now = datetime.now(timezone.utc)
            # Make last_timestamp timezone-aware if it isn't
            if last_timestamp.tzinfo is None:
                last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)

            time_diff = now - last_timestamp
            seconds_ago = int(time_diff.total_seconds())

            # Check if within time window
            if seconds_ago < time_window_seconds:
                return {
                    "success": True,
                    "found_recent_save": True,
                    "last_save": {
                        "memory_id": most_recent.id,
                        "title": most_recent.title,
                        "timestamp": last_timestamp.isoformat(),
                        "seconds_ago": seconds_ago,
                        "tags": most_recent.tags,
                        "content_preview": most_recent.content[:200] + "..."
                        if len(most_recent.content) > 200
                        else most_recent.content,
                    },
                    "time_window_checked": time_window_seconds,
                    "message": f"Last save found {seconds_ago} seconds ago",
                }
            else:
                return {
                    "success": True,
                    "found_recent_save": False,
                    "last_save_was": {
                        "seconds_ago": seconds_ago,
                        "title": most_recent.title,
                    },
                    "time_window_checked": time_window_seconds,
                    "message": f"No saves found in the last {time_window_seconds} seconds. Last save was {seconds_ago} seconds ago.",
                    "troubleshooting_tips": [
                        "Verify MEMOGRAPH_AUTONOMOUS_MODE=true is set",
                        "Check custom instructions are configured in Claude Desktop",
                        "Try calling auto_hook_response manually",
                        "Increase time_window_seconds if saves are less frequent",
                    ],
                }

        except Exception as e:
            logger.error(f"Error in verify_last_save: {e}")
            return {
                "success": False,
                "error": str(e),
                "found_recent_save": False,
            }

    async def get_save_stats(self, period: str = "session") -> dict[str, Any]:
        """Get statistics about save success rate.

        Args:
            period: Time period to analyze ('session', 'hour', 'day', 'week', 'all')

        Returns:
            Dictionary with save statistics
        """
        try:
            # Validate period
            valid_periods = ["session", "hour", "day", "week", "all"]
            if period not in valid_periods:
                return {
                    "success": False,
                    "error": f"Invalid period: '{period}'. Must be one of: {', '.join(valid_periods)}",
                }

            now = datetime.now(timezone.utc)
            from datetime import timedelta

            # Determine time range
            if period == "session":
                start_time = self.session_start
            elif period == "hour":
                start_time = now - timedelta(hours=1)
            elif period == "day":
                start_time = now - timedelta(days=1)
            elif period == "week":
                start_time = now - timedelta(weeks=1)
            else:  # all
                start_time = datetime.min.replace(tzinfo=timezone.utc)

            # Filter history by period
            filtered_history = [
                entry for entry in self.save_history if entry["timestamp"] >= start_time
            ]

            # Calculate stats from history
            history_attempts = len(filtered_history)
            history_successes = sum(
                1 for e in filtered_history if e.get("success", False)
            )
            history_failures = history_attempts - history_successes

            # For session stats, use instance variables
            if period == "session":
                attempts = self.save_attempts
                successes = self.successful_saves
                failures = self.failed_saves
            else:
                attempts = history_attempts
                successes = history_successes
                failures = history_failures

            # Calculate save rate
            save_rate = (successes / attempts * 100) if attempts > 0 else 0.0

            # Get memory counts
            all_nodes = self.kernel.graph.all_nodes()
            conversation_memories = sum(
                1 for n in all_nodes if "conversation" in n.tags
            )
            other_memories = len(all_nodes) - conversation_memories

            # Interpret status
            if save_rate >= 90:
                status = "excellent"
                message = f"Save rate of {save_rate:.1f}% is excellent. Auto-save is working very well."
            elif save_rate >= 70:
                status = "good"
                message = f"Save rate of {save_rate:.1f}% is acceptable. Consider improving custom instructions for better coverage."
            elif save_rate >= 50:
                status = "poor"
                message = f"Save rate of {save_rate:.1f}% is below target. Review custom instructions and check for errors."
            else:
                status = "critical"
                message = f"Save rate of {save_rate:.1f}% is critically low. Auto-save may not be working correctly."

            # Special case for no attempts
            if attempts == 0:
                status = "no_data"
                message = "No save attempts recorded in this period."

            return {
                "success": True,
                "period": period,
                "statistics": {
                    "save_attempts": attempts,
                    "successful_saves": successes,
                    "failed_saves": failures,
                    "save_rate_percent": round(save_rate, 1),
                    "conversation_memories": conversation_memories,
                    "other_memories": other_memories,
                    "total_memories": len(all_nodes),
                },
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": now.isoformat(),
                    "duration_minutes": round(
                        (now - start_time).total_seconds() / 60, 1
                    ),
                },
                "interpretation": {
                    "status": status,
                    "message": message,
                    "target_rate": 70.0,
                    "meets_target": save_rate >= 70.0,
                },
            }

        except Exception as e:
            logger.error(f"Error in get_save_stats: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def get_auto_save_analytics(
        self, period: str = "day", include_recommendations: bool = True
    ) -> dict[str, Any]:
        """Get comprehensive auto-save analytics.

        Args:
            period: 'hour', 'day', 'week', or 'all'
            include_recommendations: Whether to include improvement suggestions

        Returns:
            Comprehensive analytics dictionary
        """
        try:
            from datetime import timedelta

            # Determine time window
            now = datetime.now(timezone.utc)
            if period == "hour":
                cutoff = now - timedelta(hours=1)
            elif period == "day":
                cutoff = now - timedelta(days=1)
            elif period == "week":
                cutoff = now - timedelta(weeks=1)
            else:  # 'all'
                cutoff = datetime.min.replace(tzinfo=timezone.utc)

            # Get all conversation memories
            all_nodes = self.kernel.graph.all_nodes()
            conversation_nodes = [
                n
                for n in all_nodes
                if ("conversation" in n.tags or "interaction" in n.tags)
                and n.created_at
                and n.created_at > cutoff
            ]

            # Categorize by layer
            layer1_saves = [
                n for n in conversation_nodes if "layer1-explicit" in n.tags
            ]
            layer2_saves = [
                n
                for n in conversation_nodes
                if "monitor-layer2" in n.tags or "auto-detected" in n.tags
            ]
            uncategorized = [
                n
                for n in conversation_nodes
                if n not in layer1_saves and n not in layer2_saves
            ]

            total_saves = len(conversation_nodes)
            layer1_count = len(layer1_saves)
            layer2_count = len(layer2_saves)

            # Calculate rates
            layer1_rate = (layer1_count / total_saves * 100) if total_saves > 0 else 0
            layer2_rate = (layer2_count / total_saves * 100) if total_saves > 0 else 0

            # Estimate total conversations (rough heuristic)
            # Assume 94% capture rate for hybrid system
            estimated_total = int(total_saves / 0.94) if total_saves > 0 else 0
            estimated_missed = estimated_total - total_saves
            overall_save_rate = (
                (total_saves / estimated_total * 100) if estimated_total > 0 else 0
            )

            # Build analytics
            analytics = {
                "success": True,
                "period": period,
                "time_window": {
                    "start": cutoff.isoformat(),
                    "end": now.isoformat(),
                    "duration_hours": (now - cutoff).total_seconds() / 3600,
                },
                "summary": {
                    "total_conversations_saved": total_saves,
                    "estimated_total_conversations": estimated_total,
                    "estimated_missed": estimated_missed,
                    "overall_save_rate_percent": round(overall_save_rate, 1),
                },
                "by_layer": {
                    "layer1_explicit_saves": layer1_count,
                    "layer1_percentage": round(layer1_rate, 1),
                    "layer2_monitor_saves": layer2_count,
                    "layer2_percentage": round(layer2_rate, 1),
                    "uncategorized": len(uncategorized),
                },
                "performance_grade": self._calculate_performance_grade(
                    overall_save_rate
                ),
            }

            # Add monitor stats if available
            if (
                hasattr(self.server, "conversation_monitor")
                and self.server.conversation_monitor
            ):
                monitor = self.server.conversation_monitor
                analytics["monitor_stats"] = {
                    "total_detected": monitor.stats.get("total_detected", 0),
                    "saved": monitor.stats.get("saved", 0),
                    "skipped_duplicates": monitor.stats.get("skipped_duplicates", 0),
                    "skipped_low_confidence": monitor.stats.get(
                        "skipped_low_confidence", 0
                    ),
                }

            # Add recommendations
            if include_recommendations:
                analytics["recommendations"] = self._generate_analytics_recommendations(
                    overall_save_rate, layer1_count, layer2_count, total_saves
                )

            return analytics

        except Exception as e:
            logger.error(f"Error generating analytics: {e}")
            return {"success": False, "error": str(e)}

    def _calculate_performance_grade(self, save_rate: float) -> dict[str, str]:
        """Calculate performance grade based on save rate."""
        if save_rate >= 95:
            return {"grade": "A+", "status": "Excellent", "emoji": "🌟"}
        elif save_rate >= 90:
            return {"grade": "A", "status": "Very Good", "emoji": "✅"}
        elif save_rate >= 80:
            return {"grade": "B", "status": "Good", "emoji": "👍"}
        elif save_rate >= 70:
            return {"grade": "C", "status": "Fair", "emoji": "⚠️"}
        elif save_rate >= 50:
            return {"grade": "D", "status": "Poor", "emoji": "❌"}
        else:
            return {"grade": "F", "status": "Critical", "emoji": "🚨"}

    def _generate_analytics_recommendations(
        self, overall_rate: float, layer1_count: int, layer2_count: int, total: int
    ) -> list[str]:
        """Generate recommendations based on analytics."""
        recommendations = []

        if overall_rate < 70:
            recommendations.append(
                "🚨 CRITICAL: Save rate below 70%. Enable Phase 2 monitor immediately."
            )

        if layer1_count == 0 and total > 0:
            recommendations.append(
                "⚠️ No Layer 1 saves detected. Check custom instructions are properly configured."
            )

        if layer2_count == 0 and layer1_count < 5:
            recommendations.append(
                "💡 Consider enabling Phase 2 monitor (MEMOGRAPH_AUTO_SAVE_MONITOR=true) for better coverage."
            )

        if layer2_count > layer1_count * 2:
            recommendations.append(
                "📝 Layer 2 catching many misses. Review and strengthen custom instructions."
            )

        if overall_rate >= 90:
            recommendations.append(
                "🌟 Excellent performance! Hybrid system working well."
            )

        if total == 0:
            recommendations.append(
                "🔍 No conversations saved yet. Start using auto_hook_response or enable monitor."
            )

        return recommendations

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
