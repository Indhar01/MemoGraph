"""Bidirectional sync between Obsidian and MemoGraph.

This module provides full bidirectional synchronization between an Obsidian vault
and MemoGraph's memory system, handling conflicts, tracking state, and maintaining
consistency across both systems.
"""

import hashlib
import asyncio
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Callable, Tuple
from datetime import datetime
from collections import deque

from memograph import MemoryKernel
from memograph.core.enums import MemoryType
from .parser import ObsidianParser
from .sync_state import SyncState
from .conflict_resolver import ConflictResolver, ConflictStrategy
from .performance_metrics import get_tracker


# Type alias for progress callback
# Callback receives: (current_index, total_files, current_file_path, status)
ProgressCallback = Callable[[int, int, str, str], None]


class BatchSyncCancelled(Exception):
    """Exception raised when batch sync is cancelled."""

    pass


class ObsidianSync:
    """Bidirectional sync between Obsidian and MemoGraph."""

    def __init__(
        self,
        vault_path: Path,
        memograph_vault: Path,
        conflict_strategy: ConflictStrategy = ConflictStrategy.NEWEST_WINS,
        enable_queue: bool = True,
        max_queue_size: int = 100,
        rate_limit_delay: float = 1.0,
    ):
        """Initialize Obsidian sync manager.

        Args:
            vault_path: Path to the Obsidian vault directory
            memograph_vault: Path to the MemoGraph vault directory
            conflict_strategy: Strategy for resolving sync conflicts
            enable_queue: Enable sync queue for rate limiting
            max_queue_size: Maximum number of files in sync queue
            rate_limit_delay: Minimum delay between sync operations (seconds)
        """
        self.vault_path = Path(vault_path)
        self.memograph_vault = Path(memograph_vault)
        self.kernel = MemoryKernel(str(memograph_vault))
        self.parser = ObsidianParser(cache_size=256)  # Enable LRU caching
        self.state = SyncState(
            memograph_vault / ".obsidian_sync_state.json", use_sqlite=True
        )
        self.resolver = ConflictResolver(conflict_strategy)
        self.perf_tracker = get_tracker()

        # Sync queue configuration
        self.enable_queue = enable_queue
        self.max_queue_size = max_queue_size
        self.rate_limit_delay = rate_limit_delay

        # Sync queue state
        self._sync_queue: deque = deque(maxlen=max_queue_size)
        self._queued_files: Set[str] = set()
        self._queue_lock = asyncio.Lock()
        self._is_syncing = False
        self._last_sync_time = 0.0
        self._queue_processor_task: Optional[asyncio.Task] = None

        # Batch sync state
        self._batch_cancelled = False
        self._current_batch_progress: Dict[str, Any] = {}

        # Error tracking
        self._error_history: List[Dict[str, Any]] = []
        self._error_count = 0
        self._error_rate_limit = (
            10  # Max errors before stopping (lowered for better safety)
        )
        self._last_error_time = 0.0

        # Ensure vault paths exist
        self.vault_path.mkdir(parents=True, exist_ok=True)
        self.memograph_vault.mkdir(parents=True, exist_ok=True)

    async def sync(self, direction: str = "bidirectional") -> Dict[str, Any]:
        """Perform sync operation.

        Args:
            direction: Sync direction - "pull", "push", or "bidirectional"

        Returns:
            Dictionary with sync statistics:
                - pulled: Number of notes pulled from Obsidian
                - pushed: Number of notes pushed to Obsidian
                - conflicts: Number of conflicts encountered
                - errors: List of error messages
                - duration: Duration in seconds
                - timestamp: ISO timestamp of sync completion
        """
        import time

        start_time = time.time()
        stats = {"pulled": 0, "pushed": 0, "conflicts": 0, "errors": []}
        self._is_syncing = True

        with self.perf_tracker.track_operation("sync", direction=direction):
            try:
                # Ensure graph is loaded (only if empty)
                if not self.kernel.graph or not list(self.kernel.graph.all_nodes()):
                    self.kernel.ingest()

                if direction in ["pull", "bidirectional"]:
                    try:
                        pull_stats = await self.pull_from_obsidian()
                        stats["pulled"] = pull_stats["count"]
                        stats["conflicts"] += pull_stats["conflicts"]
                        if "errors" in pull_stats and pull_stats["errors"]:
                            stats["errors"].extend(pull_stats["errors"])
                    except (ConnectionError, TimeoutError, ConnectionRefusedError) as e:
                        error_msg = f"Network error during pull: {str(e)}"
                        stats["errors"].append(error_msg)
                        self._record_error(e, transient=True)

                if direction in ["push", "bidirectional"]:
                    try:
                        push_stats = await self.push_to_obsidian()
                        stats["pushed"] = push_stats["count"]
                        stats["conflicts"] += push_stats["conflicts"]
                        if "errors" in push_stats and push_stats["errors"]:
                            stats["errors"].extend(push_stats["errors"])
                    except (ConnectionError, TimeoutError, ConnectionRefusedError) as e:
                        error_msg = f"Network error during push: {str(e)}"
                        stats["errors"].append(error_msg)
                        self._record_error(e, transient=True)

                self.state.mark_synced()

            except Exception as e:
                self.perf_tracker.record_error()
                stats["errors"].append(str(e))
            finally:
                self._is_syncing = False
                stats["duration"] = time.time() - start_time
                stats["timestamp"] = datetime.now().isoformat()

        return stats

    async def queue_file_sync(
        self, file_path: str, event_type: str = "modified"
    ) -> bool:
        """Add a file to the sync queue.

        Args:
            file_path: Path to the file to sync
            event_type: Type of event (created, modified, deleted)

        Returns:
            True if file was queued, False if queue is full or file already queued
        """
        if not self.enable_queue:
            # If queue disabled, sync immediately
            await self.sync_single_file(file_path, event_type)
            return True

        async with self._queue_lock:
            # Check if file is already in queue
            if file_path in self._queued_files:
                return False

            # Check if queue is full
            if len(self._sync_queue) >= self.max_queue_size:
                return False

            # Add to queue
            self._sync_queue.append((file_path, event_type, time.time()))
            self._queued_files.add(file_path)

        # Start queue processor if not running
        if not self._queue_processor_task or self._queue_processor_task.done():
            self._queue_processor_task = asyncio.create_task(self._process_sync_queue())

        return True

    async def _process_sync_queue(self):
        """Process files in the sync queue with rate limiting."""
        while True:
            async with self._queue_lock:
                if not self._sync_queue:
                    # Queue is empty, stop processing
                    break

                # Get next file from queue
                file_path, event_type, queue_time = self._sync_queue.popleft()
                self._queued_files.discard(file_path)

            # Apply rate limiting
            current_time = time.time()
            time_since_last_sync = current_time - self._last_sync_time
            if time_since_last_sync < self.rate_limit_delay:
                await asyncio.sleep(self.rate_limit_delay - time_since_last_sync)

            # Sync the file
            try:
                await self.sync_single_file(file_path, event_type)
                self._last_sync_time = time.time()
            except Exception as e:
                print(f"Error syncing queued file {file_path}: {e}")

    async def sync_single_file(self, file_path: str, event_type: str = "modified"):
        """Sync a single file immediately.

        Args:
            file_path: Path to the file to sync
            event_type: Type of event (created, modified, deleted)
        """
        file_path_obj = Path(file_path)

        # Handle deleted files
        if event_type == "deleted" or (
            event_type != "created" and not file_path_obj.exists()
        ):
            # Find and remove memory associated with this path
            existing = self._find_memory_by_path(str(file_path_obj))
            if existing:
                # Delete the memory file
                memory_file = self.memograph_vault / f"{existing.id}.md"
                if memory_file.exists():
                    memory_file.unlink()
                # Remove from graph
                self.kernel.graph.remove_node(existing.id)
                # Clear from state
                self.state.update_file_hash(str(file_path_obj), "")
            return

        # Ensure file exists and is markdown
        if not file_path_obj.exists() or file_path_obj.suffix != ".md":
            return

        try:
            # Parse file
            note_data = self.parser.parse_file(file_path_obj)
            file_size = file_path_obj.stat().st_size
            file_mtime = file_path_obj.stat().st_mtime

            # Check if already synced and unchanged
            current_hash = self._hash_content(note_data["content"])
            if not self.state.has_file_changed(str(file_path_obj), current_hash):
                self.perf_tracker.record_cache_hit()
                return

            self.perf_tracker.record_cache_miss()

            # Check if exists in MemoGraph
            existing = self._find_memory_by_path(str(file_path_obj))

            if existing:
                # Check for conflicts
                existing_data = self._node_to_dict(existing)
                if self.resolver.detect_conflict(note_data, existing_data):
                    resolved = self.resolver.resolve(note_data, existing_data)
                    self.state.add_conflict(
                        str(file_path_obj),
                        f"Content conflict resolved using {self.resolver.strategy.value}",
                    )
                else:
                    resolved = note_data
            else:
                resolved = note_data

            # Import to MemoGraph
            memory_type = self._parse_memory_type(
                resolved.get("metadata", {}).get("memory_type")
            )

            node_id = await self.kernel.remember_async(
                title=resolved["title"],
                content=resolved["content"],
                memory_type=memory_type,
                tags=resolved.get("tags", []),
                salience=resolved.get("metadata", {}).get("salience", 0.5),
                meta={
                    **resolved.get("metadata", {}),
                    "source": "obsidian",
                    "obsidian_path": str(file_path_obj),
                    "sync_timestamp": datetime.now().isoformat(),
                },
            )

            # Remove any duplicate memories pointing to the same file
            # Only for OBSIDIAN_WINS strategy to avoid interfering with other strategies
            if node_id and self.resolver.strategy == ConflictStrategy.OBSIDIAN_WINS:
                self._remove_duplicate_memories(str(file_path_obj), node_id)

            # Update sync state with file metadata
            self.state.update_file_hash(
                str(file_path_obj), current_hash, file_size, file_mtime
            )
            self.perf_tracker.record_file_processed(file_size)

        except Exception as e:
            print(f"Error syncing file {file_path}: {e}")
            raise

    def get_queue_status(self) -> Dict[str, Any]:
        """Get current sync queue status.

        Returns:
            Dictionary with queue statistics:
                - queue_enabled: Whether queue is enabled
                - queue_size: Number of files in queue
                - queued_files: List of queued file paths
                - is_syncing: Whether actively syncing
                - last_sync_time: Timestamp of last sync
                - max_queue_size: Maximum queue capacity
                - rate_limit_delay: Rate limiting delay in seconds
        """
        return {
            "queue_enabled": self.enable_queue,
            "queue_size": len(self._sync_queue),
            "queued_files": list(self._queued_files),
            "is_syncing": self._is_syncing,
            "last_sync_time": self._last_sync_time,
            "max_queue_size": self.max_queue_size,
            "rate_limit_delay": self.rate_limit_delay,
        }

    async def batch_sync(
        self,
        file_paths: Optional[List[Path]] = None,
        direction: str = "bidirectional",
        batch_size: int = 50,
        progress_callback: Optional[ProgressCallback] = None,
        enable_rollback: bool = False,
    ) -> Dict[str, Any]:
        """Perform batch sync operation on multiple files efficiently.

        Args:
            file_paths: List of file paths to sync. If None, syncs all markdown files.
            direction: Sync direction - "pull", "push", or "bidirectional"
            batch_size: Number of files to process in each batch
            progress_callback: Optional callback for progress updates
                Called with (current_index, total_files, current_file_path, status)
            enable_rollback: Enable automatic rollback on critical errors

        Returns:
            Dictionary with batch sync statistics:
                - pulled: Number of notes pulled
                - pushed: Number of notes pushed
                - conflicts: Number of conflicts
                - errors: List of error messages
                - cancelled: Whether the operation was cancelled
                - processed: Number of files processed
                - duration: Duration in seconds
                - timestamp: ISO timestamp of completion
                - rolled_back: Whether state was rolled back (if enable_rollback=True)
        """
        import time

        start_time = time.time()
        stats = {
            "pulled": 0,
            "pushed": 0,
            "conflicts": 0,
            "errors": [],
            "cancelled": False,
            "processed": 0,
            "rolled_back": False,
        }

        # Reset cancellation flag and set syncing state
        self._batch_cancelled = False
        self._is_syncing = True

        # Create checkpoint if rollback is enabled
        checkpoint = None
        if enable_rollback:
            checkpoint = self.state.create_checkpoint()

        try:
            # Ensure graph is loaded (only if empty)
            if not self.kernel.graph or not list(self.kernel.graph.all_nodes()):
                self.kernel.ingest()

            # Get files to process based on direction
            if file_paths is None:
                if direction == "push":
                    # For push-only, get paths from memories, not from vault scanning
                    all_nodes = list(self.kernel.graph.all_nodes())
                    obsidian_memories = [
                        node
                        for node in all_nodes
                        if node.frontmatter.get("meta", {}).get("source") == "obsidian"
                    ]
                    file_paths = []
                    for memory in obsidian_memories:
                        obsidian_path = memory.frontmatter.get("meta", {}).get(
                            "obsidian_path"
                        )
                        if obsidian_path:
                            file_paths.append(Path(obsidian_path))
                elif direction == "bidirectional":
                    # For bidirectional, combine vault files AND memory paths
                    vault_files = set(self.vault_path.rglob("*.md"))

                    # Get paths from memories
                    all_nodes = list(self.kernel.graph.all_nodes())
                    obsidian_memories = [
                        node
                        for node in all_nodes
                        if node.frontmatter.get("meta", {}).get("source") == "obsidian"
                    ]
                    memory_paths = set()
                    for memory in obsidian_memories:
                        obsidian_path = memory.frontmatter.get("meta", {}).get(
                            "obsidian_path"
                        )
                        if obsidian_path:
                            memory_paths.add(Path(obsidian_path))

                    # Combine both sets
                    file_paths = list(vault_files | memory_paths)
                else:
                    # For pull-only, scan vault for existing files
                    file_paths = list(self.vault_path.rglob("*.md"))
            else:
                file_paths = [Path(p) for p in file_paths]

            total_files = len(file_paths)

            # Process files in batches
            for batch_start in range(0, total_files, batch_size):
                # Check for cancellation
                if self._batch_cancelled:
                    stats["cancelled"] = True
                    break

                # Check if error rate limit exceeded BEFORE processing batch
                if len(stats.get("errors", [])) >= self._error_rate_limit:
                    stats["rate_limited"] = True
                    if "Error rate limit exceeded" not in str(stats.get("errors", [])):
                        stats["errors"].append(
                            f"Error rate limit exceeded ({len(stats['errors'])} errors)"
                        )
                    break

                batch_end = min(batch_start + batch_size, total_files)
                batch = file_paths[batch_start:batch_end]

                # Update progress tracking
                self._current_batch_progress = {
                    "files_processed": batch_start,
                    "total_files": total_files,
                    "current_batch_start": batch_start,
                    "current_batch_end": batch_end,
                }

                # Process batch
                if direction in ["pull", "bidirectional"]:
                    pull_stats = await self._batch_pull(
                        batch,
                        batch_start,
                        total_files,
                        progress_callback,
                    )
                    stats["pulled"] += pull_stats["count"]
                    stats["conflicts"] += pull_stats["conflicts"]
                    stats["errors"].extend(pull_stats.get("errors", []))
                    stats["processed"] += pull_stats["count"]

                if direction in ["push", "bidirectional"] and not self._batch_cancelled:
                    push_stats = await self._batch_push(
                        batch,
                        batch_start,
                        total_files,
                        progress_callback,
                    )
                    stats["pushed"] += push_stats["count"]
                    stats["conflicts"] += push_stats["conflicts"]
                    stats["errors"].extend(push_stats.get("errors", []))

                # Allow other tasks to run between batches (including cancellation)
                await asyncio.sleep(0.02)

            if not stats["cancelled"]:
                self.state.mark_synced()

        except BatchSyncCancelled:
            stats["cancelled"] = True
        except Exception as e:
            stats["errors"].append(f"Batch sync failed: {str(e)}")

            # Rollback on critical error if enabled
            if enable_rollback and checkpoint and self._is_critical_error(e):
                try:
                    self.state.restore_checkpoint(checkpoint)
                    stats["rolled_back"] = True
                except Exception as rollback_error:
                    stats["errors"].append(f"Rollback failed: {str(rollback_error)}")
        finally:
            self._is_syncing = False
            self._current_batch_progress = {}
            stats["duration"] = time.time() - start_time
            stats["timestamp"] = datetime.now().isoformat()

        return stats

    async def _batch_pull(
        self,
        file_paths: List[Path],
        batch_offset: int,
        total_files: int,
        progress_callback: Optional[ProgressCallback],
    ) -> Dict[str, Any]:
        """Pull a batch of files from Obsidian to MemoGraph.

        Args:
            file_paths: List of file paths to pull
            batch_offset: Offset for progress reporting
            total_files: Total number of files being processed
            progress_callback: Optional progress callback

        Returns:
            Dictionary with pull statistics
        """
        stats = {"count": 0, "conflicts": 0, "errors": []}

        for idx, md_file in enumerate(file_paths):
            # Yield to the event loop on every file so that concurrent tasks
            # (e.g. a cancellation coroutine sleeping for a real-time delay)
            # get a chance to run and advance their timers.
            await asyncio.sleep(0)

            if self._batch_cancelled:
                raise BatchSyncCancelled()

            current_idx = batch_offset + idx

            if progress_callback:
                progress_callback(
                    current_idx + 1,
                    total_files,
                    str(md_file),
                    "pulling",
                )

            # Skip if file doesn't exist
            if not md_file.exists():
                continue

            try:
                # Parse Obsidian note
                note_data = self.parser.parse_file(md_file)
                file_size = md_file.stat().st_size
                file_mtime = md_file.stat().st_mtime

                # Check if already synced and unchanged
                current_hash = self._hash_content(note_data["content"])
                if not self.state.has_file_changed(str(md_file), current_hash):
                    self.perf_tracker.record_cache_hit()
                    continue

                self.perf_tracker.record_cache_miss()

                # Check if exists in MemoGraph by path
                existing = self._find_memory_by_path(str(md_file))

                # If not found by path, check by title (file may have been moved)
                if not existing:
                    existing = self._find_memory_by_title(note_data["title"])
                    if existing:
                        # File was moved - update the path in metadata
                        old_path = existing.frontmatter.get("meta", {}).get(
                            "obsidian_path"
                        )
                        if old_path and old_path != str(md_file):
                            # This is a moved file, we'll update it
                            pass

                if existing:
                    # Check for conflicts
                    existing_data = self._node_to_dict(existing)
                    if self.resolver.detect_conflict(note_data, existing_data):
                        resolved = self.resolver.resolve(note_data, existing_data)
                        stats["conflicts"] += 1
                        self.state.add_conflict(
                            str(md_file),
                            f"Content conflict resolved using {self.resolver.strategy.value}",
                        )
                    else:
                        resolved = note_data
                else:
                    resolved = note_data

                # Import to MemoGraph
                memory_type = self._parse_memory_type(
                    resolved.get("metadata", {}).get("memory_type")
                )

                try:
                    node_id = await self.kernel.remember_async(
                        title=resolved["title"],
                        content=resolved["content"],
                        memory_type=memory_type,
                        tags=resolved.get("tags", []),
                        salience=resolved.get("metadata", {}).get("salience", 0.5),
                        meta={
                            **resolved.get("metadata", {}),
                            "source": "obsidian",
                            "obsidian_path": str(md_file),
                            "sync_timestamp": datetime.now().isoformat(),
                        },
                    )

                    # Remove any duplicate memories pointing to the same file
                    # Only for OBSIDIAN_WINS strategy to avoid interfering with other strategies
                    if (
                        node_id
                        and self.resolver.strategy == ConflictStrategy.OBSIDIAN_WINS
                    ):
                        self._remove_duplicate_memories(str(md_file), node_id)

                except Exception as remember_error:
                    # Record error
                    self._record_error(
                        remember_error,
                        transient=self._is_transient_error(remember_error),
                    )
                    # Re-raise critical errors for rollback handling
                    if self._is_critical_error(remember_error):
                        raise
                    # For non-critical errors, let outer handler catch and continue
                    raise

                # Update sync state with file metadata
                self.state.update_file_hash(
                    str(md_file), current_hash, file_size, file_mtime
                )
                self.perf_tracker.record_file_processed(file_size)
                stats["count"] += 1

            except Exception as e:
                # Check if this is a critical error that should trigger rollback
                if self._is_critical_error(e):
                    # Re-raise critical errors to propagate to batch_sync
                    raise

                # For non-critical errors, record and continue
                self._record_error(e, transient=self._is_transient_error(e))
                error_msg = f"{md_file}: {str(e)}"
                if "errors" not in stats:
                    stats["errors"] = []
                stats["errors"].append(error_msg)
                # Continue processing other files
                continue

        return stats

    async def _batch_push(
        self,
        file_paths: List[Path],
        batch_offset: int,
        total_files: int,
        progress_callback: Optional[ProgressCallback],
    ) -> Dict[str, Any]:
        """Push a batch of memories from MemoGraph to Obsidian.

        Args:
            file_paths: List of file paths that should be pushed
            batch_offset: Offset for progress reporting
            total_files: Total number of files being processed
            progress_callback: Optional progress callback

        Returns:
            Dictionary with push statistics
        """
        stats = {"count": 0, "conflicts": 0, "errors": []}

        # Get all memories with obsidian source
        all_nodes = list(self.kernel.graph.all_nodes())
        obsidian_memories = [
            node
            for node in all_nodes
            if node.frontmatter.get("meta", {}).get("source") == "obsidian"
        ]

        # Filter to only memories whose paths are in the batch
        file_paths_str = {str(p) for p in file_paths}
        batch_memories = [
            memory
            for memory in obsidian_memories
            if memory.frontmatter.get("meta", {}).get("obsidian_path") in file_paths_str
        ]

        for idx, memory in enumerate(batch_memories):
            if self._batch_cancelled:
                raise BatchSyncCancelled()

            try:
                obsidian_path = memory.frontmatter.get("meta", {}).get("obsidian_path")
                if not obsidian_path:
                    continue

                file_path = Path(obsidian_path)

                if progress_callback:
                    current_idx = batch_offset + idx
                    progress_callback(
                        current_idx + 1,
                        total_files,
                        str(file_path),
                        "pushing",
                    )

                # Get memory data
                memory_data = self._node_to_dict(memory)

                # Check if file exists in Obsidian
                if file_path.exists():
                    # Read current Obsidian content
                    current = self.parser.parse_file(file_path)

                    # Check for conflicts
                    if self.resolver.detect_conflict(current, memory_data):
                        resolved = self.resolver.resolve(
                            current, memory_data, str(file_path)
                        )
                        stats["conflicts"] += 1
                        self.state.add_conflict(
                            str(file_path),
                            f"Content conflict resolved using {self.resolver.strategy.value}",
                        )
                    else:
                        resolved = memory_data
                else:
                    resolved = memory_data

                # Write to Obsidian
                self._write_obsidian_file(file_path, resolved)

                # Update sync state
                file_hash = self._hash_content(resolved["content"])
                self.state.update_file_hash(str(file_path), file_hash)

                stats["count"] += 1

            except Exception as e:
                stats["errors"].append(f"{memory.id}: {str(e)}")

        return stats

    def cancel_batch_sync(self) -> bool:
        """Cancel an ongoing batch sync operation.

        Returns:
            True if a batch sync was in progress and will be cancelled
        """
        if self._is_syncing:
            self._batch_cancelled = True
            return True
        return False

    def get_batch_progress(self) -> Dict[str, Any]:
        """Get current batch sync progress.

        Returns:
            Dictionary with current batch progress information:
                - is_syncing: Whether batch sync is active
                - cancelled: Whether batch sync was cancelled
                - current_file: Currently processing file (if any)
                - files_processed: Number of files processed
                - total_files: Total files to process
                - progress_percentage: Progress as percentage (0-100)
        """
        progress = {
            "is_syncing": self._is_syncing,
            "cancelled": self._batch_cancelled,
            **self._current_batch_progress,
        }

        # Calculate progress percentage if data available
        if "files_processed" in progress and "total_files" in progress:
            total = progress["total_files"]
            if total > 0:
                progress["progress_percentage"] = (
                    progress["files_processed"] / total
                ) * 100
            else:
                progress["progress_percentage"] = 0

        return progress

    async def pull_from_obsidian(self) -> Dict[str, Any]:
        """Pull notes from Obsidian to MemoGraph.

        Returns:
            Dictionary with pull statistics:
                - count: Number of notes pulled
                - conflicts: Number of conflicts
                - errors: List of error messages
        """
        stats = {"count": 0, "conflicts": 0, "errors": []}

        # Get all markdown files from Obsidian vault
        md_files = list(self.vault_path.rglob("*.md"))

        # Detect and handle file deletions
        # Get all tracked files and check if they still exist
        tracked_files = set(self.state.get_tracked_files())
        existing_files = {str(f) for f in md_files}
        deleted_files = tracked_files - existing_files

        for deleted_file in deleted_files:
            # Find and remove memory associated with this deleted file
            existing = self._find_memory_by_path(deleted_file)
            if existing:
                # Delete the memory file
                memory_file = self.memograph_vault / f"{existing.id}.md"
                if memory_file.exists():
                    memory_file.unlink()
                # Remove from graph
                self.kernel.graph.remove_node(existing.id)
            # Remove from state tracking
            self.state.remove_file(deleted_file)

        for md_file in md_files:
            # Skip if file doesn't exist
            if not md_file.exists():
                continue

            try:
                # Parse Obsidian note
                note_data = self.parser.parse_file(md_file)
                file_size = md_file.stat().st_size
                file_mtime = md_file.stat().st_mtime

                # Check if already synced and unchanged
                current_hash = self._hash_content(note_data["content"])
                if not self.state.has_file_changed(str(md_file), current_hash):
                    self.perf_tracker.record_cache_hit()
                    continue

                self.perf_tracker.record_cache_miss()

                # Check if exists in MemoGraph by path
                existing = self._find_memory_by_path(str(md_file))

                # If not found by path, check by title (file may have been moved)
                if not existing:
                    existing = self._find_memory_by_title(note_data["title"])
                    if existing:
                        # File was moved - update old path tracking
                        old_path = existing.frontmatter.get("meta", {}).get(
                            "obsidian_path"
                        )
                        if old_path and old_path != str(md_file):
                            # Remove old path from tracking
                            self.state.remove_file(old_path)

                if existing:
                    # Check for conflicts
                    existing_data = self._node_to_dict(existing)
                    if self.resolver.detect_conflict(note_data, existing_data):
                        resolved = self.resolver.resolve(note_data, existing_data)
                        stats["conflicts"] += 1
                        self.state.add_conflict(
                            str(md_file),
                            f"Content conflict resolved using {self.resolver.strategy.value}",
                        )
                    else:
                        resolved = note_data
                else:
                    resolved = note_data

                # Import to MemoGraph
                memory_type = self._parse_memory_type(
                    resolved.get("metadata", {}).get("memory_type")
                )

                try:
                    node_id = await self.kernel.remember_async(
                        title=resolved["title"],
                        content=resolved["content"],
                        memory_type=memory_type,
                        tags=resolved.get("tags", []),
                        salience=resolved.get("metadata", {}).get("salience", 0.5),
                        meta={
                            **resolved.get("metadata", {}),
                            "source": "obsidian",
                            "obsidian_path": str(md_file),
                            "sync_timestamp": datetime.now().isoformat(),
                        },
                    )

                    # Remove any duplicate memories pointing to the same file
                    # Only for OBSIDIAN_WINS strategy to avoid interfering with other strategies
                    if (
                        node_id
                        and self.resolver.strategy == ConflictStrategy.OBSIDIAN_WINS
                    ):
                        self._remove_duplicate_memories(str(md_file), node_id)

                except Exception as remember_error:
                    # Record error and re-raise to outer handler
                    self._record_error(
                        remember_error,
                        transient=self._is_transient_error(remember_error),
                    )
                    raise

                # Update sync state with file metadata
                self.state.update_file_hash(
                    str(md_file), current_hash, file_size, file_mtime
                )
                self.perf_tracker.record_file_processed(file_size)
                stats["count"] += 1

            except Exception as e:
                error_msg = f"{md_file}: {str(e)}"
                print(f"Error syncing {md_file}: {e}")
                self._record_error(e, transient=self._is_transient_error(e))
                stats["errors"].append(error_msg)
                # Continue processing other files
                continue

        return stats

    async def push_to_obsidian(self) -> Dict[str, Any]:
        """Push memories from MemoGraph to Obsidian.

        Returns:
            Dictionary with push statistics:
                - count: Number of memories pushed
                - conflicts: Number of conflicts
        """
        stats = {"count": 0, "conflicts": 0}

        # Get all memories with obsidian source
        all_nodes = list(self.kernel.graph.all_nodes())
        obsidian_memories = [
            node
            for node in all_nodes
            if node.frontmatter.get("meta", {}).get("source") == "obsidian"
        ]

        for memory in obsidian_memories:
            try:
                obsidian_path = memory.frontmatter.get("meta", {}).get("obsidian_path")
                if not obsidian_path:
                    continue

                file_path = Path(obsidian_path)

                # Get memory data
                memory_data = self._node_to_dict(memory)

                # Check if file exists in Obsidian
                if file_path.exists():
                    # Read current Obsidian content
                    current = self.parser.parse_file(file_path)

                    # Check for conflicts
                    if self.resolver.detect_conflict(current, memory_data):
                        resolved = self.resolver.resolve(
                            current, memory_data, str(file_path)
                        )
                        stats["conflicts"] += 1
                        self.state.add_conflict(
                            str(file_path),
                            f"Content conflict resolved using {self.resolver.strategy.value}",
                        )
                    else:
                        resolved = memory_data
                else:
                    resolved = memory_data

                # Write to Obsidian
                self._write_obsidian_file(file_path, resolved)

                # Update sync state with file metadata
                file_hash = self._hash_content(resolved["content"])
                file_size = file_path.stat().st_size if file_path.exists() else 0
                file_mtime = file_path.stat().st_mtime if file_path.exists() else 0.0
                self.state.update_file_hash(
                    str(file_path), file_hash, file_size, file_mtime
                )
                self.perf_tracker.record_file_processed(file_size)

                stats["count"] += 1

            except Exception as e:
                print(f"Error pushing {memory.id}: {e}")
                stats["errors"] = stats.get("errors", [])
                stats["errors"].append(f"{memory.id}: {str(e)}")

        return stats

    def _find_memory_by_path(self, obsidian_path: str) -> Optional[Any]:
        """Find a memory in MemoGraph by its Obsidian path.

        Args:
            obsidian_path: Path to the Obsidian file

        Returns:
            MemoryNode if found, None otherwise
        """
        for node in self.kernel.graph.all_nodes():
            if node.frontmatter.get("meta", {}).get("obsidian_path") == obsidian_path:
                return node
        return None

    def _find_memory_by_title(self, title: str) -> Optional[Any]:
        """Find a memory by title (for detecting moved files).

        Args:
            title: Memory title to search for

        Returns:
            MemoryNode if found, None otherwise
        """
        for node in self.kernel.graph.all_nodes():
            if (
                node.title == title
                and node.frontmatter.get("meta", {}).get("source") == "obsidian"
            ):
                return node
        return None

    def _find_all_memories_by_path(self, obsidian_path: str) -> List[Any]:
        """Find all memories in MemoGraph by Obsidian path.

        Args:
            obsidian_path: Path to the Obsidian file

        Returns:
            List of MemoryNodes with matching obsidian_path
        """
        matches = []
        for node in self.kernel.graph.all_nodes():
            if node.frontmatter.get("meta", {}).get("obsidian_path") == obsidian_path:
                matches.append(node)
        return matches

    def _remove_duplicate_memories(self, obsidian_path: str, keep_node_id: str) -> int:
        """Remove duplicate memories pointing to same obsidian_path.

        Args:
            obsidian_path: Path to the Obsidian file
            keep_node_id: ID of the node to keep

        Returns:
            Number of duplicate memories removed
        """
        all_matches = self._find_all_memories_by_path(obsidian_path)
        removed = 0

        for node in all_matches:
            if node.id != keep_node_id:
                # Remove duplicate memory from graph and delete its file
                try:
                    # Delete the file from disk
                    file_path = self.memograph_vault / f"{node.id}.md"
                    if file_path.exists():
                        file_path.unlink()

                    # Remove from graph
                    self.kernel.graph.remove_node(node.id)
                    removed += 1
                except Exception as e:
                    print(f"Warning: Failed to remove duplicate memory {node.id}: {e}")

        return removed

    def _node_to_dict(self, node: Any) -> Dict[str, Any]:
        """Convert a MemoryNode to a dictionary format.

        Args:
            node: MemoryNode to convert

        Returns:
            Dictionary with node data
        """
        return {
            "title": node.title,
            "content": node.content,
            "tags": list(node.tags) if hasattr(node, "tags") else [],
            "metadata": dict(node.frontmatter) if hasattr(node, "frontmatter") else {},
            "modified": node.created_at.timestamp()
            if hasattr(node, "created_at")
            else 0,
        }

    def _parse_memory_type(self, type_str: Optional[str]) -> MemoryType:
        """Parse memory type string to MemoryType enum.

        Args:
            type_str: String representation of memory type

        Returns:
            MemoryType enum value
        """
        if not type_str:
            return MemoryType.FACT

        type_map = {
            "episodic": MemoryType.EPISODIC,
            "semantic": MemoryType.SEMANTIC,
            "procedural": MemoryType.PROCEDURAL,
            "fact": MemoryType.FACT,
        }

        return type_map.get(type_str.lower(), MemoryType.FACT)

    def _hash_content(self, content: str) -> str:
        """Hash content for comparison.

        Args:
            content: Content string to hash

        Returns:
            MD5 hash of the content
        """
        return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()

    def _write_obsidian_file(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Write data to Obsidian markdown file.

        Args:
            file_path: Path to write to
             Data dictionary with title, content, tags, metadata
        """
        import frontmatter

        # Create frontmatter (exclude sync-specific metadata)
        metadata = {
            k: v
            for k, v in data.get("metadata", {}).items()
            if k not in ["source", "obsidian_path", "sync_timestamp"]
        }

        # Create frontmatter post
        post = frontmatter.Post(data["content"], **metadata)
        post["title"] = data["title"]
        if data.get("tags"):
            post["tags"] = data["tags"]

        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))

    def get_sync_status(self) -> Dict[str, Any]:
        """Get current sync status and statistics.

        Returns:
            Dictionary with sync status information:
                - last_sync: Timestamp of last sync
                - tracked_files: Number of tracked files
                - conflicts: List of file paths with unresolved conflicts
                - is_syncing: Whether a sync is currently in progress
                - queue_status: Current sync queue status
                - batch_progress: Current batch sync progress
                - cache_stats: Cache performance statistics
                - performance_stats: Performance metrics
                - state_stats: Sync state database statistics
        """
        # Get conflicts and extract just the file paths for easier checking
        conflicts = self.state.get_conflicts()
        conflict_paths = [c["file_path"] for c in conflicts]

        return {
            "last_sync": self.state.get_last_sync(),
            "tracked_files": len(self.state.get_tracked_files()),
            "conflicts": conflict_paths,
            "is_syncing": self._is_syncing,
            "queue_status": self.get_queue_status(),
            "batch_progress": self.get_batch_progress(),
            "cache_stats": self.parser.get_cache_stats(),
            "performance_stats": self.perf_tracker.get_operation_summary("sync"),
            "state_stats": self.state.get_statistics() if self.state.use_sqlite else {},
        }

    def resolve_conflict_manually(self, file_path: str) -> bool:
        """Mark a conflict as manually resolved.

        Args:
            file_path: Path to the file whose conflict is resolved

        Returns:
            True if conflict was found and removed, False otherwise
        """
        return self.state.resolve_conflict(file_path)

    def clear_all_conflicts(self) -> int:
        """Clear all tracked conflicts.

        Returns:
            Number of conflicts cleared
        """
        return self.state.clear_conflicts()

    # Error handling and retry methods

    async def _retry_with_backoff(
        self,
        operation: Callable,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        retryable_exceptions: Tuple = (ConnectionError, TimeoutError, OSError),
    ) -> Any:
        """Retry an async operation with exponential backoff.

        Args:
            operation: Async callable to retry
            max_attempts: Maximum number of retry attempts
            initial_delay: Initial delay in seconds
            retryable_exceptions: Tuple of exception types that should trigger retry

        Returns:
            Result of the operation

        Raises:
            The last exception if all retries fail
        """
        delay = initial_delay
        last_exception = None

        for attempt in range(max_attempts):
            try:
                return await operation()
            except retryable_exceptions as e:
                last_exception = e
                self._record_error(e, transient=True)

                if attempt < max_attempts - 1:
                    # Wait with exponential backoff
                    await asyncio.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    # Last attempt failed
                    raise
            except Exception as e:
                # Non-retryable exception
                self._record_error(e, transient=False)
                raise

        # Should not reach here, but just in case
        if last_exception:
            raise last_exception

    async def _sync_file_with_retry(
        self,
        file_path: str,
        max_attempts: int = 3,
    ) -> None:
        """Sync a single file with retry logic.

        Args:
            file_path: Path to the file to sync
            max_attempts: Maximum number of retry attempts
        """
        await self._retry_with_backoff(
            lambda: self.sync_single_file(file_path),
            max_attempts=max_attempts,
            initial_delay=0.5,
            retryable_exceptions=(
                ConnectionError,
                TimeoutError,
                PermissionError,
                OSError,
            ),
        )

    def _is_transient_error(self, error: Exception) -> bool:
        """Check if an error is transient (temporary).

        Args:
            error: Exception to check

        Returns:
            True if error is transient, False otherwise
        """
        transient_types = (
            ConnectionError,
            TimeoutError,
            ConnectionRefusedError,
            ConnectionResetError,
            ConnectionAbortedError,
            OSError,  # Network unreachable, etc.
        )

        return isinstance(error, transient_types)

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable.

        Args:
            error: Exception to check

        Returns:
            True if error is retryable, False otherwise
        """
        retryable_types = (
            ConnectionError,
            TimeoutError,
            PermissionError,  # File locks
            BlockingIOError,
            OSError,
        )

        # Check specific OSError codes
        if isinstance(error, OSError):
            # Windows file lock error code
            if hasattr(error, "winerror") and error.winerror == 32:
                return True
            # Unix EACCES (13) or EAGAIN (11)
            if hasattr(error, "errno") and error.errno in (13, 11):
                return True

        return isinstance(error, retryable_types)

    def _is_critical_error(self, error: Exception) -> bool:
        """Check if an error is critical and should trigger rollback.

        Args:
            error: Exception to check

        Returns:
            True if error is critical, False otherwise
        """
        # Transient errors are not critical
        if self._is_transient_error(error):
            return False

        # Critical error types
        critical_types = (
            RuntimeError,
            SystemError,
            MemoryError,
            KeyboardInterrupt,
        )

        return isinstance(error, critical_types)

    def _record_error(self, error: Exception, transient: bool = False) -> None:
        """Record an error in the error history.

        Args:
            error: Exception that occurred
            transient: Whether the error is transient
        """
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "error_type": type(error).__name__,
            "message": str(error),
            "transient": transient,
        }

        self._error_history.append(error_entry)
        self._error_count += 1
        self._last_error_time = time.time()

        # Trim history to last 100 errors
        if len(self._error_history) > 100:
            self._error_history = self._error_history[-100:]

    def get_error_history(self) -> List[Dict[str, Any]]:
        """Get the error history.

        Returns:
            List of error dictionaries
        """
        return self._error_history.copy()

    def clear_error_history(self) -> int:
        """Clear the error history.

        Returns:
            Number of errors cleared
        """
        count = len(self._error_history)
        self._error_history.clear()
        self._error_count = 0
        return count
