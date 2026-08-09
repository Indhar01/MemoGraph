"""File system watcher for Obsidian vault changes."""

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from pathlib import Path
from typing import Callable, Optional, Dict, Any
import asyncio
import threading
import logging
import time

logger = logging.getLogger(__name__)


class ObsidianWatcher(FileSystemEventHandler):
    """Watch Obsidian vault for changes.

    This watcher monitors an Obsidian vault directory for changes to markdown files
    and triggers callbacks for file creation, modification, and deletion events.

    Attributes:
        vault_path: Path to the Obsidian vault directory
        on_change: Async callback function to handle file changes
        observer: Watchdog observer instance
        loop: Event loop for async operations
    """

    def __init__(
        self,
        vault_path: Path | str,
        on_change: Callable[[str, str], None] | Callable[[str, str], asyncio.Future],
        debounce_delay: float = 0.3,
    ):
        """Initialize the Obsidian watcher.

        Args:
            vault_path: Path to the Obsidian vault to watch
            on_change: Callback function that takes (file_path, event_type) as arguments.
                      Can be sync or async.
            debounce_delay: Delay in seconds before triggering callback (default: 0.3s)

        Raises:
            ValueError: If vault_path does not exist or is not a directory
        """
        # Convert to Path object and validate immediately
        vault_path_obj = Path(vault_path)

        # Validate path exists and is a directory before storing
        if not vault_path_obj.exists():
            raise ValueError(f"Vault path does not exist: {vault_path}")
        if not vault_path_obj.is_dir():
            raise ValueError(f"Vault path is not a directory: {vault_path}")

        # Store validated path
        self.vault_path = vault_path_obj
        self.on_change = on_change
        self.observer: Optional[Observer] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.debounce_delay = debounce_delay

        # Debouncing state: file_path -> (last_event_time, event_type, timer_task)
        # timer_task can be asyncio.Task or threading.Timer depending on callback type
        self._pending_events: Dict[str, tuple[float, str, Any]] = {}

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Start watching the vault.

        Args:
            loop: Event loop to use for async callbacks. If None, tries to get current loop.
        """
        if self.observer is not None:
            logger.warning("Watcher is already running")
            return

        # Try to get event loop
        try:
            self.loop = loop or asyncio.get_event_loop()
        except RuntimeError:
            # No event loop in current thread, create new one
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

        self.observer = Observer()
        # Run the watchdog observer as a daemon thread so a caller that forgets
        # to stop() (or a crashed teardown) can never keep the interpreter
        # alive at exit — a common cause of hangs on Windows CI runners.
        self.observer.daemon = True
        self.observer.schedule(self, str(self.vault_path), recursive=True)
        self.observer.start()
        logger.info(f"Started watching vault: {self.vault_path}")

    def stop(self):
        """Stop watching the vault."""
        if self.observer is None:
            logger.warning("Watcher is not running")
            return

        # Cancel all pending timer tasks
        for event_path, (_, _, timer_task) in list(self._pending_events.items()):
            if timer_task is not None:
                if isinstance(timer_task, threading.Timer):
                    timer_task.cancel()
                elif hasattr(timer_task, "cancel"):
                    timer_task.cancel()
        self._pending_events.clear()

        self.observer.stop()
        # Bounded join: on Windows a stuck observer thread must not block
        # shutdown indefinitely (it's a daemon, so exit is safe regardless).
        self.observer.join(timeout=5)
        self.observer = None
        logger.info(f"Stopped watching vault: {self.vault_path}")

    def _should_process(self, event: FileSystemEvent) -> bool:
        """Check if event should be processed.

        Args:
            event: File system event

        Returns:
            True if event should be processed, False otherwise
        """
        if event.is_directory:
            return False

        file_path = Path(event.src_path)
        return file_path.suffix == ".md"

    def _handle_event(self, event_path: str, event_type: str):
        """Handle file system event with debouncing.

        Args:
            event_path: Path to the file that changed
            event_type: Type of event (created, modified, deleted)
        """
        # Check if callback is async - if not, we can call it synchronously without event loop
        is_async_callback = asyncio.iscoroutinefunction(self.on_change)

        if is_async_callback:
            # Async callback requires event loop
            if not self.loop or not self.loop.is_running():
                logger.warning(
                    f"Event loop not running, cannot process async {event_type} event for {event_path}"
                )
                return

            # Cancel any existing pending event for this file
            if event_path in self._pending_events:
                _, _, existing_task = self._pending_events[event_path]
                if existing_task and not existing_task.done():
                    existing_task.cancel()

            # Schedule new debounced event
            current_time = time.time()
            self._pending_events[event_path] = (current_time, event_type, None)

            # Create async task for debounced callback
            task = asyncio.run_coroutine_threadsafe(
                self._debounced_callback(event_path, event_type, current_time),
                self.loop,
            )

            # Update with the task reference
            self._pending_events[event_path] = (current_time, event_type, task)
        else:
            # Synchronous callback - execute directly with simple debouncing
            current_time = time.time()

            # Cancel any existing pending timer for this file
            if event_path in self._pending_events:
                _, _, existing_timer = self._pending_events[event_path]
                if existing_timer is not None:
                    existing_timer.cancel()

            # Schedule new debounced callback using threading.Timer
            def execute_sync_callback():
                """Execute the synchronous callback after debounce delay."""
                try:
                    # Check if this is still the latest event for this file
                    if event_path in self._pending_events:
                        pending_time, pending_type, _ = self._pending_events[event_path]
                        if pending_time == current_time:
                            # This is still the latest event, execute callback
                            logger.debug(
                                f"Executing debounced {pending_type} callback for {event_path}"
                            )
                            self.on_change(event_path, pending_type)
                            # Remove from pending events
                            del self._pending_events[event_path]
                        else:
                            logger.debug(
                                f"Skipping outdated {event_type} event for {event_path}"
                            )
                except Exception as e:
                    logger.error(f"Error in sync callback for {event_path}: {e}")
                    # Clean up on error
                    if event_path in self._pending_events:
                        del self._pending_events[event_path]

            timer = threading.Timer(self.debounce_delay, execute_sync_callback)
            # Daemon so a pending debounce timer never blocks interpreter exit.
            timer.daemon = True
            timer.start()

            # Store with timer reference
            self._pending_events[event_path] = (current_time, event_type, timer)

    async def _debounced_callback(
        self, event_path: str, event_type: str, event_time: float
    ):
        """Execute callback after debounce delay.

        Args:
            event_path: Path to the file that changed
            event_type: Type of event
            event_time: Timestamp when event was registered
        """
        try:
            # Wait for debounce delay
            await asyncio.sleep(self.debounce_delay)

            # Check if this is still the latest event for this file
            if event_path in self._pending_events:
                pending_time, pending_type, _ = self._pending_events[event_path]
                if pending_time == event_time:
                    # This is still the latest event, execute callback
                    logger.debug(
                        f"Executing debounced {pending_type} callback for {event_path}"
                    )

                    # Check if callback is async
                    if asyncio.iscoroutinefunction(self.on_change):
                        await self.on_change(event_path, pending_type)
                    else:
                        # Call sync callback
                        self.on_change(event_path, pending_type)

                    # Remove from pending events
                    del self._pending_events[event_path]
                else:
                    logger.debug(
                        f"Skipping outdated {event_type} event for {event_path}"
                    )

        except asyncio.CancelledError:
            logger.debug(f"Debounced callback cancelled for {event_path}")
        except Exception as e:
            logger.error(f"Error in debounced callback for {event_path}: {e}")
            # Clean up on error
            if event_path in self._pending_events:
                del self._pending_events[event_path]

    def on_modified(self, event: FileSystemEvent):
        """Handle file modification events.

        Args:
            event: File system event
        """
        if not self._should_process(event):
            return

        logger.debug(f"File modified: {event.src_path}")
        self._handle_event(event.src_path, "modified")

    def on_created(self, event: FileSystemEvent):
        """Handle file creation events.

        Args:
            event: File system event
        """
        if not self._should_process(event):
            return

        logger.debug(f"File created: {event.src_path}")
        self._handle_event(event.src_path, "created")

    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion events.

        Args:
            event: File system event
        """
        if not self._should_process(event):
            return

        logger.debug(f"File deleted: {event.src_path}")
        self._handle_event(event.src_path, "deleted")

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False
