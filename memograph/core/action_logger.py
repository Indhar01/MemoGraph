"""
Action logging system for MemoGraph audit trail.

This module provides comprehensive action tracking for all memory operations,
creating an audit trail that can be queried for history and analytics.

Example:
    >>> from memograph.core.action_logger import ActionLogger, log_action
    >>>
    >>> # Log an action
    >>> log_action(
    ...     memory_id="123",
    ...     action_type="create",
    ...     summary="Created new memory: Python Tips",
    ...     metadata={"tags": ["python", "coding"]}
    ... )
    >>>
    >>> # Get recent actions
    >>> logger = ActionLogger(vault_path="./vault")
    >>> recent = logger.get_recent_actions(limit=10)
"""

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("memograph.action_logger")

ActionType = Literal["create", "update", "delete", "boost", "link", "merge", "tag"]


@dataclass
class Action:
    """Represents a single action in the history."""

    memory_id: str
    action_type: ActionType
    summary: str
    timestamp: str
    timestamp_ns: int | None = None
    metadata: dict[str, Any] | None = None
    user: str | None = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ActionLogger:
    """Logger for memory actions and operations."""

    def __init__(self, vault_path: str, history_file: str = ".memograph_history.json"):
        """Initialize action logger.

        Args:
            vault_path: Path to vault directory
            history_file: Name of history file (stored in vault root)
        """
        self.vault_path = Path(vault_path)
        self.history_path = self.vault_path / history_file
        self._lock = threading.Lock()

        # Ensure vault directory exists
        self.vault_path.mkdir(parents=True, exist_ok=True)

    def log_action(
        self,
        memory_id: str,
        action_type: ActionType,
        summary: str,
        metadata: dict[str, Any] | None = None,
        user: str | None = None,
    ) -> Action:
        """Log a memory action.

        Args:
            memory_id: ID of the memory
            action_type: Type of action performed
            summary: Human-readable summary
            metadata: Additional metadata
            user: User who performed action (optional)

        Returns:
            Created Action object

        Example:
            >>> logger = ActionLogger("./vault")
            >>> logger.log_action(
            ...     memory_id="123",
            ...     action_type="update",
            ...     summary="Updated tags",
            ...     metadata={"added_tags": ["python"], "removed_tags": ["general"]}
            ... )
        """
        action = Action(
            memory_id=memory_id,
            action_type=action_type,
            summary=summary,
            timestamp=datetime.now().isoformat(),
            timestamp_ns=time.time_ns(),
            metadata=metadata or {},
            user=user,
        )

        with self._lock:
            history = self._read_history()
            history.append(action.to_dict())
            self._write_history(history)

        logger.info(f"Action logged: {action_type} on {memory_id}")
        return action

    def get_recent_actions(
        self,
        limit: int = 100,
        action_type: ActionType | None = None,
        memory_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent actions with optional filtering.

        Args:
            limit: Maximum number of actions to return
            action_type: Filter by action type
            memory_id: Filter by memory ID

        Returns:
            List of action dictionaries

        Example:
            >>> logger = ActionLogger("./vault")
            >>> recent_creates = logger.get_recent_actions(
            ...     limit=50,
            ...     action_type="create"
            ... )
        """
        with self._lock:
            history = self._read_history()

        # Apply filters
        if action_type:
            history = [a for a in history if a.get("action_type") == action_type]

        if memory_id:
            history = [a for a in history if a.get("memory_id") == memory_id]

        # Return most recent first
        return list(reversed(history[-limit:]))

    def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        """Get all actions for a specific memory.

        Args:
            memory_id: Memory ID to get history for

        Returns:
            List of actions for the memory
        """
        return self.get_recent_actions(limit=10000, memory_id=memory_id)

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about logged actions.

        Returns:
            Dictionary with action statistics
        """
        with self._lock:
            history = self._read_history()

        if not history:
            return {
                "total_actions": 0,
                "by_type": {},
                "unique_memories": 0,
                "first_action": None,
                "last_action": None,
            }

        # Count by type
        by_type: dict[str, int] = {}
        memory_ids = set()

        for action in history:
            action_type = action.get("action_type", "unknown")
            by_type[action_type] = by_type.get(action_type, 0) + 1

            memory_id = action.get("memory_id")
            if memory_id:
                memory_ids.add(memory_id)

        return {
            "total_actions": len(history),
            "by_type": by_type,
            "unique_memories": len(memory_ids),
            "first_action": history[0].get("timestamp") if history else None,
            "last_action": history[-1].get("timestamp") if history else None,
        }

    def group_consecutive_actions(
        self, actions: list[dict[str, Any]], time_window_seconds: int = 60
    ) -> list[dict[str, Any]]:
        """Group consecutive actions on the same memory.

        Args:
            actions: List of actions to group
            time_window_seconds: Time window for grouping

        Returns:
            List of grouped actions

        Example:
            >>> actions = logger.get_recent_actions(limit=50)
            >>> grouped = logger.group_consecutive_actions(actions)
        """
        if not actions:
            return []

        grouped = []
        current_group = None

        for action in actions:
            timestamp = datetime.fromisoformat(action["timestamp"])

            if current_group is None:
                current_group = {
                    "actions": [action],
                    "memory_id": action["memory_id"],
                    "start_time": action["timestamp"],
                    "end_time": action["timestamp"],
                    "count": 1,
                }
            elif (
                current_group["memory_id"] == action["memory_id"]
                and (
                    timestamp - datetime.fromisoformat(current_group["end_time"])
                ).total_seconds()
                <= time_window_seconds
            ):
                # Add to current group
                current_group["actions"].append(action)
                current_group["end_time"] = action["timestamp"]
                current_group["count"] += 1
            else:
                # Start new group
                grouped.append(current_group)
                current_group = {
                    "actions": [action],
                    "memory_id": action["memory_id"],
                    "start_time": action["timestamp"],
                    "end_time": action["timestamp"],
                    "count": 1,
                }

        if current_group:
            grouped.append(current_group)

        return grouped

    def clear_history(self, before_date: datetime | None = None):
        """Clear action history.

        Args:
            before_date: Only clear actions before this date (None = clear all)
        """
        with self._lock:
            if before_date is None:
                self._write_history([])
                logger.info("Cleared all action history")
            else:
                history = self._read_history()
                cutoff_ns = int(before_date.timestamp() * 1_000_000_000)

                def _is_on_or_after_cutoff(action: dict[str, Any]) -> bool:
                    action_ns = action.get("timestamp_ns")
                    if isinstance(action_ns, int):
                        return action_ns >= cutoff_ns
                    return datetime.fromisoformat(action["timestamp"]) >= before_date

                filtered = [a for a in history if _is_on_or_after_cutoff(a)]
                self._write_history(filtered)
                logger.info(
                    f"Cleared {len(history) - len(filtered)} actions before {before_date}"
                )

    def _read_history(self) -> list[dict[str, Any]]:
        """Read history from file."""
        if not self.history_path.exists():
            return []

        try:
            with open(self.history_path, encoding="utf-8") as f:
                data: list[dict[str, Any]] = json.load(f)
                return data
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to read history: {e}")
            return []

    def _write_history(self, history: list[dict[str, Any]]):
        """Write history to file."""
        try:
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
        except OSError as e:
            logger.error(f"Failed to write history: {e}")


# Global logger instance
_global_logger: ActionLogger | None = None
_logger_lock = threading.Lock()


def get_action_logger(vault_path: str) -> ActionLogger:
    """Get the global action logger instance.

    Args:
        vault_path: Path to vault directory

    Returns:
        ActionLogger instance
    """
    global _global_logger

    if _global_logger is None or str(_global_logger.vault_path) != vault_path:
        with _logger_lock:
            if _global_logger is None or str(_global_logger.vault_path) != vault_path:
                _global_logger = ActionLogger(vault_path)

    return _global_logger


def log_action(
    vault_path: str,
    memory_id: str,
    action_type: ActionType,
    summary: str,
    metadata: dict[str, Any] | None = None,
    user: str | None = None,
) -> Action:
    """Convenience function to log an action.

    Args:
        vault_path: Path to vault directory
        memory_id: ID of the memory
        action_type: Type of action
        summary: Human-readable summary
        meta Additional metadata
        user: User who performed action

    Returns:
        Created Action object

    Example:
        >>> log_action(
        ...     vault_path="./vault",
        ...     memory_id="123",
        ...     action_type="create",
        ...     summary="Created: Python Tips"
        ... )
    """
    logger_instance = get_action_logger(vault_path)
    return logger_instance.log_action(memory_id, action_type, summary, metadata, user)
