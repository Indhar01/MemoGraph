"""Conflict resolution for Obsidian-MemoGraph sync.

This module provides conflict detection and resolution strategies for
bidirectional sync between Obsidian and MemoGraph.
"""

import hashlib
from enum import Enum
from typing import Dict, Any, Callable, Optional, List
from datetime import datetime


class ConflictStrategy(Enum):
    """Strategy for resolving sync conflicts."""

    OBSIDIAN_WINS = "obsidian_wins"
    MEMOGRAPH_WINS = "memograph_wins"
    NEWEST_WINS = "newest_wins"
    MANUAL = "manual"


class ConflictInfo:
    """Information about a detected conflict."""

    def __init__(
        self,
        file_path: str,
        obsidian_version: Dict[str, Any],
        memograph_version: Dict[str, Any],
    ):
        """Initialize conflict information.

        Args:
            file_path: Path to the conflicting file.
            obsidian_version: Version from Obsidian vault.
            memograph_version: Version from MemoGraph vault.
        """
        self.file_path = file_path
        self.obsidian_version = obsidian_version
        self.memograph_version = memograph_version
        self.timestamp = datetime.now()
        self.resolved = False
        self.resolution_strategy: Optional[str] = None
        self.resolved_content: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert conflict info to dictionary.

        Returns:
            Dictionary representation of conflict info.
        """
        return {
            "file_path": self.file_path,
            "obsidian_version": self.obsidian_version,
            "memograph_version": self.memograph_version,
            "timestamp": self.timestamp.isoformat(),
            "resolved": self.resolved,
            "resolution_strategy": self.resolution_strategy,
        }


class ConflictResolver:
    """Resolve sync conflicts between Obsidian and MemoGraph."""

    def __init__(
        self,
        strategy: ConflictStrategy = ConflictStrategy.NEWEST_WINS,
        ui_callback: Optional[Callable[[ConflictInfo], Dict[str, Any]]] = None,
    ):
        """Initialize conflict resolver.

        Args:
            strategy: Strategy to use for conflict resolution.
                Defaults to NEWEST_WINS.
            ui_callback: Optional callback function for UI-based conflict resolution.
                Should accept ConflictInfo and return resolution dict with 'strategy'
                and optional 'content' keys.
        """
        self.strategy = strategy
        self.ui_callback = ui_callback
        self.conflict_history: List[ConflictInfo] = []

    def detect_conflict(
        self, obsidian_version: Dict[str, Any], memograph_version: Dict[str, Any]
    ) -> bool:
        """Detect if versions conflict.

        Args:
            obsidian_version: Version from Obsidian vault.
            memograph_version: Version from MemoGraph vault.

        Returns:
            True if versions conflict, False otherwise.
        """
        # Handle None or missing content
        obs_content = obsidian_version.get("content", "")
        mem_content = memograph_version.get("content", "")

        # Handle empty content edge case
        if not obs_content and not mem_content:
            return False

        # Compare content hashes
        obs_hash = self.hash_content(obs_content)
        mem_hash = self.hash_content(mem_content)

        return obs_hash != mem_hash

    def resolve(
        self,
        obsidian_version: Dict[str, Any],
        memograph_version: Dict[str, Any],
        file_path: str = "",
    ) -> Dict[str, Any]:
        """Resolve conflict based on strategy.

        Args:
            obsidian_version: Version from Obsidian vault.
            memograph_version: Version from MemoGraph vault.
            file_path: Path to the conflicting file (for UI callback).

        Returns:
            Resolved version dictionary.
        """
        # Create conflict info for tracking
        conflict_info = ConflictInfo(file_path, obsidian_version, memograph_version)
        self.conflict_history.append(conflict_info)

        # If UI callback is set and strategy is MANUAL, use it
        if self.strategy == ConflictStrategy.MANUAL and self.ui_callback:
            try:
                ui_resolution = self.ui_callback(conflict_info)
                resolved_strategy = ui_resolution.get("strategy", "newest_wins")

                conflict_info.resolved = True
                conflict_info.resolution_strategy = resolved_strategy

                # Handle UI resolution
                if resolved_strategy == "keep-local":
                    conflict_info.resolved_content = obsidian_version.get("content")
                    return obsidian_version
                elif resolved_strategy == "keep-remote":
                    conflict_info.resolved_content = memograph_version.get("content")
                    return memograph_version
                elif resolved_strategy == "keep-both":
                    merged_content = ui_resolution.get("content")
                    if merged_content:
                        conflict_info.resolved_content = merged_content
                        return {**obsidian_version, "content": merged_content}
                    return self.create_conflict_marker(
                        obsidian_version, memograph_version
                    )
                elif resolved_strategy == "manual":
                    # User wants to manually edit - create conflict markers
                    return self.create_conflict_marker(
                        obsidian_version, memograph_version
                    )
            except Exception as e:
                # Fallback to automatic resolution if UI callback fails
                print(f"UI callback failed: {e}. Falling back to automatic resolution.")

        # Automatic resolution strategies
        if self.strategy == ConflictStrategy.OBSIDIAN_WINS:
            conflict_info.resolved = True
            conflict_info.resolution_strategy = "obsidian_wins"
            return obsidian_version

        elif self.strategy == ConflictStrategy.MEMOGRAPH_WINS:
            conflict_info.resolved = True
            conflict_info.resolution_strategy = "memograph_wins"
            return memograph_version

        elif self.strategy == ConflictStrategy.NEWEST_WINS:
            obs_time = obsidian_version.get("modified", 0)
            mem_time = memograph_version.get("modified", 0)

            conflict_info.resolved = True
            conflict_info.resolution_strategy = "newest_wins"

            # Handle identical timestamps edge case
            if obs_time == mem_time:
                # If timestamps are identical, prefer Obsidian version
                return obsidian_version

            return obsidian_version if obs_time > mem_time else memograph_version

        elif self.strategy == ConflictStrategy.MANUAL:
            # Create conflict file for manual resolution (no UI)
            conflict_info.resolution_strategy = "manual"
            return self.create_conflict_marker(obsidian_version, memograph_version)

        # Default fallback (shouldn't reach here)
        conflict_info.resolved = True
        conflict_info.resolution_strategy = "default"
        return obsidian_version

    def get_conflict_history(self) -> List[Dict[str, Any]]:
        """Get history of all conflicts.

        Returns:
            List of conflict info dictionaries.
        """
        return [conflict.to_dict() for conflict in self.conflict_history]

    def clear_conflict_history(self) -> None:
        """Clear the conflict history."""
        self.conflict_history.clear()

    def get_unresolved_conflicts(self) -> List[ConflictInfo]:
        """Get list of unresolved conflicts.

        Returns:
            List of unresolved ConflictInfo objects.
        """
        return [c for c in self.conflict_history if not c.resolved]

    def create_conflict_marker(
        self, version1: Dict[str, Any], version2: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create conflict marker for manual resolution.

        Args:
            version1: First version (typically Obsidian).
            version2: Second version (typically MemoGraph).

        Returns:
            Dictionary with conflict markers in content.
        """
        v1_content = version1.get("content", "")
        v2_content = version2.get("content", "")

        conflict_content = f"""<<<<<<< Obsidian Version
{v1_content}
=======
{v2_content}
>>>>>>> MemoGraph Version
"""

        return {**version1, "content": conflict_content, "conflict": True}

    @staticmethod
    def hash_content(content: str) -> str:
        """Hash content for comparison.

        Args:
            content: Content string to hash.

        Returns:
            MD5 hash of the content.
        """
        return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
