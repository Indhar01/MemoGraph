"""Conversation monitor for automatic conversation detection and saving.

This module implements Layer 2 of the hybrid auto-save system. It monitors
MCP tool usage patterns to detect conversations that were not explicitly saved
by the AI (Layer 1), providing automatic backup saving.

Architecture:
- Runs as background asyncio task
- Monitors tool calls for conversation patterns
- Buffers detected exchanges
- Auto-saves after idle period
- Coordinates with Layer 1 to avoid duplicates
"""

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from dataclasses import dataclass

from ..core.enums import MemoryType
from ..core.kernel import MemoryKernel

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    """Record of a tool call for pattern analysis."""

    tool_name: str
    timestamp: datetime
    args: dict[str, Any]
    result: dict[str, Any]


@dataclass
class ConversationExchange:
    """Detected conversation exchange to be saved."""

    question: str
    context: str
    timestamp: datetime
    sources: list[dict[str, Any]]
    tool_sequence: list[str]
    confidence: float  # 0.0-1.0 confidence this is a real conversation


class ConversationMonitor:
    """Monitors tool usage to automatically detect and save missed conversations.

    This class implements intelligent pattern detection:
    - Pattern 1: search_vault → query_with_context (high confidence)
    - Pattern 2: Multiple query_with_context calls (medium confidence)
    - Pattern 3: create_memory after queries (low confidence, may be manual)

    Attributes:
        kernel: MemoryKernel instance for saving memories
        enabled: Whether monitoring is active
        idle_threshold: Seconds of inactivity before saving
        min_question_length: Minimum question length to consider
        exchanges: Buffer of detected exchanges
        tool_sequence: Recent tool call history
        last_activity: Timestamp of last activity
        last_layer1_save: Timestamp of last explicit save (to avoid duplicates)
    """

    def __init__(self, kernel: MemoryKernel, config: Optional[dict[str, Any]] = None):
        """Initialize conversation monitor.

        Args:
            kernel: MemoryKernel instance for saving
            config: Configuration dictionary with keys:
                - enabled: bool (default True)
                - idle_threshold_seconds: int (default 30)
                - min_question_length: int (default 10)
                - max_buffer_size: int (default 50)
                - check_interval_seconds: int (default 5)
        """
        self.kernel = kernel
        config = config or {}

        # Configuration
        self.enabled = config.get("enabled", True)
        self.idle_threshold = config.get("idle_threshold_seconds", 30)
        self.min_question_length = config.get("min_question_length", 10)
        self.max_buffer_size = config.get("max_buffer_size", 50)
        self.check_interval = config.get("check_interval_seconds", 5)

        # State
        self.exchanges: deque[ConversationExchange] = deque(maxlen=self.max_buffer_size)
        self.tool_sequence: deque[ToolCallRecord] = deque(maxlen=20)
        self.last_activity: Optional[datetime] = None
        self.last_layer1_save: Optional[datetime] = None

        # Statistics
        self.stats = {
            "total_detected": 0,
            "saved": 0,
            "skipped_duplicates": 0,
            "skipped_low_confidence": 0,
        }

        logger.info(
            f"ConversationMonitor initialized (enabled={self.enabled}, idle_threshold={self.idle_threshold}s)"
        )

    def record_tool_call(
        self, tool_name: str, args: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """Record a tool call for pattern analysis.

        Args:
            tool_name: Name of the tool that was called
            args: Tool arguments
            result: Tool result
        """
        if not self.enabled:
            return

        self.last_activity = datetime.now(timezone.utc)

        record = ToolCallRecord(
            tool_name=tool_name,
            timestamp=datetime.now(timezone.utc),
            args=args,
            result=result,
        )

        self.tool_sequence.append(record)

        # Track explicit Layer 1 saves (both legacy and the unified turn tool)
        if tool_name in ("auto_hook_response", "auto_hook_turn"):
            self.last_layer1_save = datetime.now(timezone.utc)
            logger.debug("Layer 1 save detected - resetting duplicate detection window")

        # Analyze patterns after each tool call
        self._detect_conversation_patterns()

    def _detect_conversation_patterns(self) -> None:
        """Analyze recent tool sequence for conversation patterns."""
        if len(self.tool_sequence) < 2:
            return

        recent_tools = list(self.tool_sequence)[-10:]  # Last 10 tools

        # Pattern 1: search_vault → query_with_context (HIGH confidence)
        self._detect_pattern_search_query(recent_tools)

        # Pattern 2: Multiple query_with_context (MEDIUM confidence)
        self._detect_pattern_multiple_queries(recent_tools)

        # Pattern 3: query → create_memory (May be manual, LOW confidence)
        self._detect_pattern_query_create(recent_tools)

        # Pattern 4: any vault-question activity without a Layer 1 save in
        # this window. Best-effort stub so a forgetful client at least leaves
        # *some* breadcrumb. Cannot capture AI response text — that's not in
        # the tool stream. Lower confidence; tagged ``layer2-stub`` for audit.
        self._detect_pattern_stub_orphan(recent_tools)

    def _detect_pattern_search_query(self, recent_tools: list[ToolCallRecord]) -> None:
        """Detect: search_vault → query_with_context pattern."""
        for i in range(len(recent_tools) - 1):
            if (
                recent_tools[i].tool_name == "search_vault"
                and recent_tools[i + 1].tool_name == "query_with_context"
            ):
                query_record = recent_tools[i + 1]
                question = query_record.args.get("question", "")

                if len(question) >= self.min_question_length:
                    exchange = ConversationExchange(
                        question=question,
                        context=query_record.result.get("context", ""),
                        timestamp=query_record.timestamp,
                        sources=query_record.result.get("sources", []),
                        tool_sequence=["search_vault", "query_with_context"],
                        confidence=0.9,  # High confidence
                    )

                    self._buffer_exchange(exchange)

    def _detect_pattern_multiple_queries(
        self, recent_tools: list[ToolCallRecord]
    ) -> None:
        """Detect: Multiple query_with_context calls in sequence."""
        query_tools = [r for r in recent_tools if r.tool_name == "query_with_context"]

        if len(query_tools) >= 2:
            # Take the most recent query
            query_record = query_tools[-1]
            question = query_record.args.get("question", "")

            if len(question) >= self.min_question_length:
                exchange = ConversationExchange(
                    question=question,
                    context=query_record.result.get("context", ""),
                    timestamp=query_record.timestamp,
                    sources=query_record.result.get("sources", []),
                    tool_sequence=["query_with_context"] * len(query_tools),
                    confidence=0.7,  # Medium confidence
                )

                self._buffer_exchange(exchange)

    def _detect_pattern_query_create(self, recent_tools: list[ToolCallRecord]) -> None:
        """Detect: query_with_context → create_memory (might be manual save)."""
        for i in range(len(recent_tools) - 1):
            if (
                recent_tools[i].tool_name == "query_with_context"
                and recent_tools[i + 1].tool_name == "create_memory"
            ):
                # This might be a manual save, lower confidence
                query_record = recent_tools[i]
                question = query_record.args.get("question", "")

                if len(question) >= self.min_question_length:
                    exchange = ConversationExchange(
                        question=question,
                        context=query_record.result.get("context", ""),
                        timestamp=query_record.timestamp,
                        sources=query_record.result.get("sources", []),
                        tool_sequence=["query_with_context", "create_memory"],
                        confidence=0.4,  # Low confidence - might be duplicate
                    )

                    self._buffer_exchange(exchange)

    def _detect_pattern_stub_orphan(self, recent_tools: list[ToolCallRecord]) -> None:
        """Fallback: buffer a stub if any question-like activity has no Layer 1 save.

        Looks for the most recent ``query_with_context`` or ``search_vault``
        call and buffers a low-confidence stub if no ``auto_hook_response`` /
        ``auto_hook_turn`` call has been seen in the same window. The save
        will only include the question + tool sequence — the AI's reply is
        not visible from the MCP tool stream.
        """
        # Skip if a Layer 1 save happened within the last 2 minutes.
        if self.last_layer1_save:
            seconds_since = (
                datetime.now(timezone.utc) - self.last_layer1_save
            ).total_seconds()
            if seconds_since < 120:
                return

        # Find the most recent question-bearing call.
        for record in reversed(recent_tools):
            if record.tool_name not in ("query_with_context", "search_vault"):
                continue
            question = record.args.get("question") or record.args.get("query") or ""
            if len(question) < self.min_question_length:
                continue

            exchange = ConversationExchange(
                question=question,
                context=record.result.get("context", "")
                if isinstance(record.result, dict)
                else "",
                timestamp=record.timestamp,
                sources=record.result.get("sources", [])
                if isinstance(record.result, dict)
                else [],
                tool_sequence=[record.tool_name, "stub-orphan"],
                confidence=0.5,  # Low-medium: enough to save but flagged as stub.
            )
            self._buffer_exchange(exchange)
            return

    def _buffer_exchange(self, exchange: ConversationExchange) -> None:
        """Add exchange to buffer if not duplicate.

        Args:
            exchange: Detected conversation exchange
        """
        # Check for duplicates in buffer (same question, similar timestamp)
        for existing in self.exchanges:
            if (
                existing.question == exchange.question
                and abs((existing.timestamp - exchange.timestamp).total_seconds()) < 60
            ):
                logger.debug(
                    f"Skipping duplicate exchange: {exchange.question[:50]}..."
                )
                return

        self.exchanges.append(exchange)
        self.stats["total_detected"] += 1
        logger.debug(
            f"Buffered exchange (confidence={exchange.confidence}): {exchange.question[:50]}..."
        )

    async def monitor_loop(self) -> None:
        """Background loop that periodically checks for idle state and saves."""
        logger.info("ConversationMonitor background loop started")

        while True:
            try:
                await asyncio.sleep(self.check_interval)

                if not self.enabled:
                    continue

                if self._should_save():
                    await self._save_buffered_conversations()

            except asyncio.CancelledError:
                logger.info("ConversationMonitor loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)
                # Continue running despite errors

    def _should_save(self) -> bool:
        """Check if we should save buffered conversations.

        Returns:
            True if idle threshold reached and exchanges buffered
        """
        if not self.exchanges:
            return False

        if not self.last_activity:
            return False

        idle_time = (datetime.now(timezone.utc) - self.last_activity).total_seconds()
        return idle_time >= self.idle_threshold

    async def _save_buffered_conversations(self) -> None:
        """Save all buffered exchanges as conversation memories."""
        if not self.exchanges:
            return

        logger.info(f"Saving {len(self.exchanges)} buffered exchanges...")

        # Check if Layer 1 saved recently (within last 2 minutes)
        # If yes, these might be duplicates
        layer1_recent = False
        if self.last_layer1_save:
            seconds_since_layer1 = (
                datetime.now(timezone.utc) - self.last_layer1_save
            ).total_seconds()
            layer1_recent = seconds_since_layer1 < 120

        exchanges_to_save = list(self.exchanges)
        self.exchanges.clear()

        saved_count = 0
        skipped_count = 0

        for exchange in exchanges_to_save:
            # Skip low confidence if Layer 1 was active
            if layer1_recent and exchange.confidence < 0.6:
                logger.debug(
                    f"Skipping low-confidence exchange (Layer 1 active): {exchange.question[:50]}..."
                )
                self.stats["skipped_duplicates"] += 1
                skipped_count += 1
                continue

            # Skip very low confidence always
            if exchange.confidence < 0.4:
                logger.debug(
                    f"Skipping very low-confidence exchange: {exchange.question[:50]}..."
                )
                self.stats["skipped_low_confidence"] += 1
                skipped_count += 1
                continue

            try:
                await self._save_single_exchange(exchange)
                saved_count += 1
                self.stats["saved"] += 1
            except Exception as e:
                logger.error(f"Failed to save exchange: {e}")

        logger.info(
            f"✅ Monitor saved {saved_count} exchanges, skipped {skipped_count}"
        )

    async def check_for_layer1_duplicates(self, exchange: ConversationExchange) -> bool:
        """Check if Layer 1 already saved this exchange.

        Args:
            exchange: Exchange to check

        Returns:
            True if likely duplicate, False otherwise
        """
        # Check recent conversation memories
        all_nodes = self.kernel.graph.all_nodes()
        conversation_nodes = [
            n for n in all_nodes if "conversation" in n.tags or "interaction" in n.tags
        ]

        # Look for similar saves within 5 minutes
        recent_cutoff = exchange.timestamp - timedelta(minutes=5)
        recent_conversations = [
            n
            for n in conversation_nodes
            if n.created_at and n.created_at > recent_cutoff
        ]

        # Check for content similarity
        for node in recent_conversations:
            # Skip monitor-saved nodes (only check Layer 1)
            if "monitor-layer2" in node.tags or "auto-detected" in node.tags:
                continue

            # Check if content contains our question
            if exchange.question.lower() in node.content.lower():
                logger.debug(
                    f"Found Layer 1 duplicate for: {exchange.question[:50]}..."
                )
                return True

        return False

    async def _save_single_exchange(self, exchange: ConversationExchange) -> None:
        """Save a single exchange as a memory.

        Args:
            exchange: Exchange to save
        """
        # Check for Layer 1 duplicates
        is_duplicate = await self.check_for_layer1_duplicates(exchange)
        if is_duplicate:
            logger.info(
                f"Skipping - Layer 1 already saved: {exchange.question[:50]}..."
            )
            self.stats["skipped_duplicates"] += 1
            return

        is_stub = "stub-orphan" in exchange.tool_sequence
        title = (
            f"Stub: {exchange.question[:50]}..."
            if is_stub
            else f"Auto-detected: {exchange.question[:50]}..."
        )
        content = self._format_exchange_content(exchange)

        tags = ["conversation", "auto-detected", "monitor-layer2"]
        if is_stub:
            tags.append("layer2-stub")

        # Use asyncio.to_thread to avoid blocking
        await asyncio.to_thread(
            self.kernel.remember,
            title=title,
            content=content,
            memory_type=MemoryType.EPISODIC,
            tags=tags,
            salience=0.5 + (exchange.confidence * 0.2),  # 0.5-0.7 based on confidence
        )

        logger.info(f"Saved auto-detected conversation: {title}")

    def _format_exchange_content(self, exchange: ConversationExchange) -> str:
        """Format exchange as markdown content.

        Args:
            exchange: Exchange to format

        Returns:
            Formatted markdown content
        """
        lines = ["# Auto-Detected Conversation\n\n"]
        lines.append("**Saved By:** Layer 2 (Server Monitor)\n")
        lines.append("**Layer 1 Status:** Not saved by AI\n")
        lines.append(f"**Detection Confidence:** {exchange.confidence:.0%}\n")
        lines.append(f"**Detection Pattern:** {' → '.join(exchange.tool_sequence)}\n")
        lines.append(f"**Timestamp:** {exchange.timestamp.isoformat()}\n\n")

        lines.append("## Question\n\n")
        lines.append(f"{exchange.question}\n\n")

        if exchange.context:
            lines.append("## Context Provided\n\n")
            lines.append("Yes - context was retrieved from vault\n\n")

        if exchange.sources:
            lines.append("## Sources Referenced\n\n")
            for source in exchange.sources:
                source_id = source.get("id", "unknown")
                source_title = source.get("title", "Untitled")
                lines.append(f"- [[{source_id}]] {source_title}\n")
            lines.append("\n")

        lines.append("## Detection Pattern\n\n")
        lines.append(f"Tool sequence: {' → '.join(exchange.tool_sequence)}\n\n")

        lines.append("---\n\n")
        lines.append(
            "*This conversation was automatically detected and saved by the MemoGraph server-side monitor (Layer 2 of the hybrid auto-save system).*\n"
        )

        return "".join(lines)

    def get_stats(self) -> dict[str, Any]:
        """Get monitor statistics.

        Returns:
            Dictionary with statistics about detected and saved exchanges
        """
        return {
            "enabled": self.enabled,
            "total_detected": self.stats["total_detected"],
            "saved": self.stats["saved"],
            "skipped_duplicates": self.stats["skipped_duplicates"],
            "skipped_low_confidence": self.stats["skipped_low_confidence"],
            "currently_buffered": len(self.exchanges),
            "last_activity": self.last_activity.isoformat()
            if self.last_activity
            else None,
            "last_layer1_save": self.last_layer1_save.isoformat()
            if self.last_layer1_save
            else None,
        }
