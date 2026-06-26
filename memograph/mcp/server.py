"""MCP Server implementation for MemoGraph.

This module provides an MCP (Model Context Protocol) server that exposes
MemoGraph functionality as tools that can be used by any MCP-compatible
AI client (Claude Desktop, Cline, etc.).
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from ..core.enums import MemoryType
from ..core.kernel import MemoryKernel
from .autonomous_hooks import AutonomousHooks
from .capture_filter import VALID_MODES, CaptureMode, normalize_mode
from .conversation_monitor import ConversationMonitor
from .vault_lock import VaultLock, VaultLockError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MemoGraphMCPServer:
    """MCP server for MemoGraph vault operations.

    Exposes MemoGraph functionality as MCP tools that can be called by
    AI assistants like Claude Desktop, Cline, etc.

    Example:
        >>> server = MemoGraphMCPServer(vault_path="~/my-vault")
        >>> await server.run()
    """

    def __init__(
        self,
        vault_path: str,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ):
        """Initialize MCP server with validated vault path."""
        # Validate and resolve path
        try:
            self.vault_path = Path(vault_path).expanduser().resolve()
        except (RuntimeError, OSError) as e:
            raise ValueError(f"Invalid vault path '{vault_path}': {e}") from e

        # Verify not a file
        if self.vault_path.exists() and not self.vault_path.is_dir():
            raise ValueError(
                f"Vault path is a file, not a directory: {self.vault_path}"
            )

        # Create if needed
        if not self.vault_path.exists():
            try:
                self.vault_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created vault directory: {self.vault_path}")
            except PermissionError as e:
                raise PermissionError(
                    f"Cannot create vault at {self.vault_path}: {e}"
                ) from e

        # Verify write permissions
        if not os.access(self.vault_path, os.W_OK):
            raise PermissionError(f"No write permission for vault: {self.vault_path}")

        logger.info(f"✓ Vault validated: {self.vault_path}")

        # Read-only mode: when MEMOGRAPH_READONLY=true, refuse all vault-writing
        # MCP tools (delete/update/bulk_create/batch_*/import). Read tools stay
        # functional. Useful for shared deployments or untrusted clients.
        self.readonly = os.environ.get("MEMOGRAPH_READONLY", "false").lower() == "true"
        if self.readonly:
            logger.warning(
                "⚠️  MEMOGRAPH_READONLY=true — destructive tools (delete, "
                "update, bulk_create, batch_*, import_backup) will be refused."
            )

        # Advisory PID lock so a misconfigured second writer (another MCP
        # server, the Web UI worker, etc.) cannot silently race us on vault
        # files. Read-only servers skip this — many viewers can safely share
        # a vault. Set MEMOGRAPH_SKIP_LOCK=true to opt out (e.g. test harness).
        self._vault_lock: VaultLock | None = None
        skip_lock = os.environ.get("MEMOGRAPH_SKIP_LOCK", "false").lower() == "true"
        if not self.readonly and not skip_lock:
            lock = VaultLock(self.vault_path, role="mcp-server")
            try:
                lock.acquire()
            except VaultLockError as e:
                raise RuntimeError(str(e)) from e
            self._vault_lock = lock

        # Initialize kernel
        try:
            self.kernel = MemoryKernel(str(self.vault_path))
        except Exception as e:
            raise RuntimeError(f"Kernel init failed: {e}") from e

        self.llm_provider = llm_provider
        self.llm_model = llm_model

        # Track ingest state
        self._ingest_failed = False
        self._ingest_error: Exception | None = None

        # Auto-ingest with comprehensive tracking
        try:
            stats = self.kernel.ingest()
            logger.info(
                f"✓ Ingested: {stats['indexed']} indexed, {stats['skipped']} skipped"
            )

            # Detect suspicious scenarios
            if stats["indexed"] == 0 and stats["skipped"] == 0:
                md_files = list(self.vault_path.rglob("*.md"))
                if md_files:
                    logger.error(
                        f"❌ CRITICAL: {len(md_files)} .md files found "
                        f"but none indexed - parsing errors!"
                    )
                    self._ingest_failed = True
                    self._ingest_error = RuntimeError(
                        f"All {len(md_files)} files failed to parse"
                    )
                else:
                    logger.warning("⚠️  Empty vault - no memories found")

        except Exception as e:
            logger.error(f"❌ CRITICAL: Ingest failed: {e}", exc_info=True)
            logger.error("Server degraded - operations will fail")
            self._ingest_failed = True
            self._ingest_error = e

        # Initialize autonomous hooks (can be enabled/disabled via configuration)
        self.autonomous_hooks = AutonomousHooks(self)

        # Check if autonomous mode is enabled via environment variable
        auto_mode = (
            os.environ.get("MEMOGRAPH_AUTONOMOUS_MODE", "false").lower() == "true"
        )
        if auto_mode:
            self.autonomous_hooks.auto_search_enabled = True
            self.autonomous_hooks.auto_save_responses = True
            logger.info("Autonomous mode enabled via MEMOGRAPH_AUTONOMOUS_MODE")

        # Capture mode: the single low/mid/high dial that drives both the
        # Tier-A Claude Code Stop-hook (via the CLI) and the Tier-B unified
        # auto_hook_turn MCP tool. An unknown value falls back to "mid" so a
        # typo in the env var cannot silently disable saves.
        self.capture_mode: CaptureMode = normalize_mode(
            os.environ.get("MEMOGRAPH_CAPTURE_MODE")
        )
        logger.info(f"Capture mode: {self.capture_mode}")

        # Initialize conversation monitor if enabled (Layer 2 auto-save)
        monitor_enabled = (
            os.environ.get("MEMOGRAPH_AUTO_SAVE_MONITOR", "false").lower() == "true"
        )
        if monitor_enabled:
            self.conversation_monitor = ConversationMonitor(
                kernel=self.kernel,
                config={
                    "enabled": True,
                    "idle_threshold_seconds": int(
                        os.environ.get("MEMOGRAPH_IDLE_THRESHOLD", "30")
                    ),
                    "min_question_length": int(
                        os.environ.get("MEMOGRAPH_MIN_QUESTION_LENGTH", "10")
                    ),
                    "max_buffer_size": int(
                        os.environ.get("MEMOGRAPH_MAX_BUFFER_SIZE", "50")
                    ),
                    "check_interval_seconds": int(
                        os.environ.get("MEMOGRAPH_CHECK_INTERVAL", "5")
                    ),
                },
            )
            # Store task reference to prevent garbage collection
            # Note: Task will be started by start_monitor() after server is fully initialized
            self._monitor_task = None
            logger.info("✅ Conversation monitor initialized (Layer 2 auto-save)")
        else:
            self.conversation_monitor = None
            self._monitor_task = None
            logger.info("ℹ️  Conversation monitor disabled (using Layer 1 only)")

        if llm_provider:
            logger.info(
                f"Initialized MemoGraph MCP server with vault: {self.vault_path}, provider: {llm_provider}"
            )
        else:
            logger.info(
                f"Initialized MemoGraph MCP server with vault: {self.vault_path} (no LLM provider - client will handle answers)"
            )

    def _check_server_health(self) -> None:
        """Raise error if server is in degraded state."""
        if self._ingest_failed:
            raise RuntimeError(
                f"Server degraded due to ingest failure: {self._ingest_error}\n"
                f"Fix vault issues and restart server"
            )

    def close(self) -> None:
        """Release advisory resources (vault lock, monitor task). Idempotent."""
        if self._vault_lock is not None:
            try:
                self._vault_lock.release()
            except Exception as e:  # pragma: no cover — best-effort cleanup
                logger.warning("Vault lock release failed: %s", e)
            self._vault_lock = None

    def _readonly_refusal(self, tool_name: str) -> dict[str, Any]:
        """Build the standard error payload for a readonly-blocked tool call.

        Returned (not raised) so the MCP client receives a normal tool result
        and can surface the message to the user instead of seeing a transport
        error.
        """
        return self._add_vault_context(
            {
                "success": False,
                "error": (
                    f"Tool '{tool_name}' is disabled: server is running in "
                    "read-only mode (MEMOGRAPH_READONLY=true). Restart the "
                    "server without that env var to allow writes."
                ),
                "readonly": True,
            }
        )

    def _atomic_write(self, file_path: Path, content: str) -> None:
        """Write file atomically using temp file + rename to prevent corruption.

        Args:
            file_path: Target file path to write to
            content: Content to write

        Raises:
            OSError: If write or rename fails
        """
        temp_path = file_path.with_suffix(".tmp")
        try:
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(file_path)  # Atomic on POSIX and Windows
        except Exception:
            # Clean up temp file on failure (best effort)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass  # Best effort cleanup
            raise

    def _add_vault_context(self, response: dict[str, Any]) -> dict[str, Any]:
        """Add vault context information to any response.

        This helper ensures that AI assistants always know which vault is being used,
        reducing confusion and unnecessary clarification questions.

        Args:
            response: Original response dictionary

        Returns:
            Response with vault_context added
        """
        response["vault_context"] = {
            "path": str(self.vault_path),
            "name": self.vault_path.name,
        }
        return response

    def _add_save_notification(
        self, response: dict[str, Any], layer: str = "unknown"
    ) -> dict[str, Any]:
        """Add auto-save notification to response.

        Args:
            response: Original response
            layer: Which layer saved ('layer1', 'layer2', 'unknown')

        Returns:
            Response with notification added
        """
        notifications = {
            "layer1": "💾 Saved by: You (Layer 1 explicit save)",
            "layer2": "🤖 Saved by: Monitor (Layer 2 automatic backup)",
            "unknown": "💾 Conversation saved",
        }

        response["auto_save_notification"] = notifications.get(
            layer, notifications["unknown"]
        )
        return response

    def get_server_info(self) -> dict[str, Any]:
        """Get server configuration and metadata.

        This provides comprehensive information about the MCP server instance,
        including vault configuration and capabilities.

        Returns:
            Dictionary with server metadata
        """
        import memograph

        return {
            "name": "MemoGraph MCP Server",
            "version": memograph.__version__,
            "vault": {
                "path": str(self.vault_path),
                "name": self.vault_path.name,
                "absolute_path": str(self.vault_path.resolve()),
            },
            "llm": {
                "provider": self.llm_provider or "client-managed",
                "model": self.llm_model or "not specified",
            },
            "capabilities": {
                "answer_generation": self.llm_provider is not None,
                "context_retrieval": True,
                "graph_traversal": True,
                "embeddings": False,
            },
        }

    async def get_vault_info(self) -> dict[str, Any]:
        """Get information about the currently configured vault.

        Returns essential information about the vault being used by this
        MCP server instance. Use this when you need to confirm vault location.

        Returns:
            Dictionary with vault configuration details
        """
        try:
            return {
                "success": True,
                "vault": {
                    "path": str(self.vault_path),
                    "name": self.vault_path.name,
                    "exists": self.vault_path.exists(),
                    "absolute_path": str(self.vault_path.resolve()),
                },
                "llm_config": {
                    "provider": self.llm_provider or "none (client-managed)",
                    "model": self.llm_model or "not specified",
                },
                "message": f"Currently using vault: {self.vault_path.name} at {self.vault_path}",
            }
        except Exception as e:
            logger.error(f"Error getting vault info: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def search_vault(
        self,
        query: str,
        tags: list[str] | None = None,
        top_k: int = 8,
        depth: int = 2,
        memory_type: str | None = None,
    ) -> dict[str, Any]:
        """Search memories in the vault.

        Args:
            query: Search query string
            tags: Optional list of tags to filter by
            top_k: Maximum number of results to return
            depth: Graph traversal depth
            memory_type: Optional memory type filter

        Returns:
            Dictionary with search results
        """
        try:
            self._check_server_health()
            # Retrieve nodes
            results = self.kernel.retrieve_nodes(
                query=query,
                tags=tags,
                depth=depth,
                top_k=top_k,
            )

            # Filter by memory type if specified
            if memory_type:
                try:
                    mem_type = MemoryType(memory_type)
                    results = [n for n in results if n.memory_type == mem_type]
                except ValueError:
                    pass

            # Format results
            formatted_results = [
                {
                    "id": node.id,
                    "title": node.title,
                    "content": node.content[:500] + "..."
                    if len(node.content) > 500
                    else node.content,
                    "memory_type": node.memory_type.value,
                    "tags": node.tags,
                    "salience": node.salience,
                    "created_at": node.created_at.isoformat()
                    if node.created_at
                    else None,
                }
                for node in results
            ]

            result = self._add_vault_context(
                {
                    "success": True,
                    "count": len(formatted_results),
                    "results": formatted_results,
                }
            )

            # Record for conversation monitor
            if self.conversation_monitor:
                self.conversation_monitor.record_tool_call(
                    tool_name="search_vault",
                    args={"query": query, "tags": tags, "top_k": top_k},
                    result=result,
                )

            return result

        except Exception as e:
            logger.error(f"Error searching vault: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                    "results": [],
                }
            )

    async def create_memory(
        self,
        title: str,
        content: str,
        memory_type: str = "semantic",
        tags: list[str] | None = None,
        salience: float = 0.7,
    ) -> dict[str, Any]:
        """Create a new memory in the vault.

        Args:
            title: Memory title
            content: Memory content
            memory_type: Type of memory (episodic, semantic, procedural, fact)
            tags: Optional list of tags
            salience: Importance score (0.0-1.0)

        Returns:
            Dictionary with creation result
        """
        try:
            self._check_server_health()
            if self.readonly:
                return self._readonly_refusal("create_memory")
            # Create memory
            path = self.kernel.remember(
                title=title,
                content=content,
                memory_type=MemoryType(memory_type),
                tags=tags or [],
                salience=salience,
            )

            # Find suggested links based on shared tags and keyword overlap
            # Optimized: limit candidate pool instead of checking all nodes
            suggested_links = []
            new_tags = set(tags or [])
            title_words = set(title.lower().split())
            content_words = set(w.lower() for w in content.split() if len(w) > 3)
            check_words = title_words | content_words

            # Limit candidate pool - only check memories with shared tags
            candidates = []
            if new_tags:
                candidates = self.kernel.graph.get_by_tags(
                    list(new_tags), match_all=False
                )
            else:
                # If no tags, just check recent memories
                all_nodes = self.kernel.graph.all_nodes()
                from datetime import datetime

                candidates = sorted(
                    all_nodes, key=lambda n: n.created_at or datetime.min, reverse=True
                )[:100]  # Limit to 100 most recent

            for node in candidates:
                if node.source_path and Path(node.source_path) == Path(path):
                    continue
                reasons = []
                shared_tags = new_tags & set(node.tags)
                if shared_tags:
                    reasons.append(f"shared tags: {', '.join(shared_tags)}")
                node_words = set(node.title.lower().split())
                overlap = check_words & node_words
                if overlap:
                    reasons.append(f"keyword overlap: {', '.join(list(overlap)[:3])}")
                if reasons:
                    suggested_links.append(
                        {
                            "id": node.id,
                            "title": node.title,
                            "reason": "; ".join(reasons),
                        }
                    )
                    if len(suggested_links) >= 5:  # Stop at 5 suggestions
                        break

            # Already limited to 5 in loop above

            result = self._add_vault_context(
                {
                    "success": True,
                    "message": f"Created memory: {title}",
                    "path": path,
                    "title": title,
                    "suggested_links": suggested_links,
                }
            )

            # Record for conversation monitor
            if self.conversation_monitor:
                self.conversation_monitor.record_tool_call(
                    tool_name="create_memory",
                    args={"title": title, "tags": tags, "memory_type": memory_type},
                    result=result,
                )

            return result

        except Exception as e:
            logger.error(f"Error creating memory: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def query_with_context(
        self,
        question: str,
        tags: list[str] | None = None,
        top_k: int = 8,
        provider: str | None = None,
        model: str | None = None,
        generate_answer: bool = True,
    ) -> dict[str, Any]:
        """Ask a question with vault context.

        Args:
            question: Question to ask
            tags: Optional tag filter
            top_k: Number of memories to use as context
            provider: LLM provider override
            model: Model name override
            generate_answer: If True and LLM available, generate answer.
                           If False, return context for client to use.

        Returns:
            Dictionary with answer (if LLM available) or context (for client to use)
        """
        try:
            self._check_server_health()
            from ..core.assistant import (
                build_answer_prompt,
                retrieve_cited_context,
                run_answer,
            )

            # Get context from vault (core functionality - no LLM needed)
            context, sources = retrieve_cited_context(
                kernel=self.kernel,
                query=question,
                tags=tags,
                top_k=top_k,
            )

            # Format sources
            formatted_sources = [
                {
                    "id": src.source_id,
                    "title": src.title,
                    "memory_type": src.memory_type,
                    "tags": src.tags,
                }
                for src in sources
            ]

            # Determine effective provider
            effective_provider = provider or self.llm_provider

            # If LLM provider configured and answer generation requested, generate answer
            if effective_provider and generate_answer:
                prompt = build_answer_prompt(context=context, query=question)
                model = model or self.llm_model

                answer = run_answer(
                    provider=effective_provider,
                    prompt=prompt,
                    model=model,
                    stream=False,  # No streaming for MCP
                )

                result = self._add_vault_context(
                    {
                        "success": True,
                        "answer": answer,
                        "sources": formatted_sources,
                        "question": question,
                        "mode": "generated",
                    }
                )

                # Record for conversation monitor
                if self.conversation_monitor:
                    self.conversation_monitor.record_tool_call(
                        tool_name="query_with_context",
                        args={"question": question, "tags": tags, "top_k": top_k},
                        result=result,
                    )

                return result

            # Otherwise, return context for client's LLM to use
            else:
                result = self._add_vault_context(
                    {
                        "success": True,
                        "context": context,
                        "sources": formatted_sources,
                        "question": question,
                        "mode": "context_only",
                        "message": "Use the provided context to answer the question. The context includes relevant memories from the vault with source citations [S1], [S2], etc.",
                    }
                )

                # Record for conversation monitor (even in context_only mode)
                if self.conversation_monitor:
                    self.conversation_monitor.record_tool_call(
                        tool_name="query_with_context",
                        args={"question": question, "tags": tags, "top_k": top_k},
                        result=result,
                    )

                return result

        except ImportError as e:
            # An optional extra is missing (e.g. memograph[anthropic] for the
            # claude provider). Surface the install hint in a structured way
            # so the MCP client can show it to the user.
            logger.error(f"query_with_context missing optional dependency: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                    "missing_dependency": True,
                    "hint": (
                        "Install the matching optional extra, e.g. "
                        "pip install 'memograph[anthropic]' for "
                        "MEMOGRAPH_PROVIDER=claude or "
                        "pip install 'memograph[ollama]' for "
                        "MEMOGRAPH_PROVIDER=ollama."
                    ),
                }
            )
        except Exception as e:
            logger.error(f"Error querying with context: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def get_vault_stats(self, detailed: bool = False) -> dict[str, Any]:
        """Get statistics about the vault.

        Args:
            detailed: If True, include detailed breakdowns

        Returns:
            Dictionary with vault statistics
        """
        try:
            self._check_server_health()
            # Ingest to get indexed/skipped stats
            ingest_stats = self.kernel.ingest(force=False)

            # Get comprehensive statistics using new method
            vault_stats = self.kernel.get_vault_statistics(detailed=detailed)

            # Combine both
            return self._add_vault_context(
                {
                    "success": True,
                    "vault_path": str(self.vault_path),
                    "indexed": ingest_stats["indexed"],
                    "skipped": ingest_stats["skipped"],
                    **vault_stats,
                }
            )

        except Exception as e:
            logger.error(f"Error getting vault stats: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def list_memories(
        self,
        limit: int = 20,
        memory_type: str | None = None,
        tags: list[str] | None = None,
        sort_by: str = "created",
    ) -> dict[str, Any]:
        """List memories with optional filters.

        Args:
            limit: Maximum number of memories to return
            memory_type: Filter by memory type
            tags: Filter by tags
            sort_by: Sort by field (created, salience, title)

        Returns:
            Dictionary with list of memories
        """
        try:
            self._check_server_health()
            # Get all nodes
            nodes = self.kernel.graph.all_nodes()

            # Apply filters
            if memory_type:
                try:
                    mem_type = MemoryType(memory_type)
                    nodes = [n for n in nodes if n.memory_type == mem_type]
                except ValueError:
                    pass

            if tags:
                nodes = [n for n in nodes if any(tag in n.tags for tag in tags)]

            # Sort
            if sort_by == "created":
                nodes.sort(key=lambda n: n.created_at or "", reverse=True)
            elif sort_by == "salience":
                nodes.sort(key=lambda n: n.salience, reverse=True)
            elif sort_by == "title":
                nodes.sort(key=lambda n: n.title)

            # Limit
            nodes = nodes[:limit]

            # Format
            formatted = [
                {
                    "id": node.id,
                    "title": node.title,
                    "memory_type": node.memory_type.value,
                    "tags": node.tags,
                    "salience": node.salience,
                    "created_at": node.created_at.isoformat()
                    if node.created_at
                    else None,
                    "preview": node.content[:200] + "..."
                    if len(node.content) > 200
                    else node.content,
                }
                for node in nodes
            ]

            return self._add_vault_context(
                {
                    "success": True,
                    "count": len(formatted),
                    "memories": formatted,
                }
            )

        except Exception as e:
            logger.error(f"Error listing memories: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                    "memories": [],
                }
            )

    async def get_memory(self, memory_id: str) -> dict[str, Any]:
        """Get full content of a specific memory.

        Args:
            memory_id: ID of the memory to retrieve

        Returns:
            Dictionary with memory details
        """
        try:
            self._check_server_health()
            node = self.kernel.graph.get(memory_id)

            if not node:
                return self._add_vault_context(
                    {
                        "success": False,
                        "error": f"Memory not found: {memory_id}",
                    }
                )

            return self._add_vault_context(
                {
                    "success": True,
                    "memory": {
                        "id": node.id,
                        "title": node.title,
                        "content": node.content,
                        "memory_type": node.memory_type.value,
                        "tags": node.tags,
                        "links": node.links,
                        "backlinks": node.backlinks,
                        "salience": node.salience,
                        "created_at": node.created_at.isoformat()
                        if node.created_at
                        else None,
                        "modified_at": node.modified_at.isoformat()
                        if node.modified_at
                        else None,
                    },
                }
            )

        except Exception as e:
            logger.error(f"Error getting memory: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def import_document(
        self,
        file_path: str,
        tags: list[str] | None = None,
        memory_type: str = "episodic",
        salience: float = 0.7,
    ) -> dict[str, Any]:
        """Import a document (TXT, PDF, DOCX) into the vault.

        Args:
            file_path: Path to the document to import
            tags: Optional tags to add
            memory_type: Memory type for imported document
            salience: Importance score

        Returns:
            Dictionary with import result
        """
        try:
            self._check_server_health()
            if self.readonly:
                return self._readonly_refusal("import_document")
            # Read file content
            import_path = Path(file_path).expanduser()
            if not import_path.exists():
                return self._add_vault_context(
                    {"success": False, "error": f"File not found: {file_path}"}
                )

            if import_path.suffix.lower() not in (".txt", ".md"):
                return self._add_vault_context(
                    {
                        "success": False,
                        "error": f"Unsupported file type: {import_path.suffix}. "
                        "Supported: .txt, .md",
                    }
                )

            content = import_path.read_text(encoding="utf-8")
            title = import_path.stem.replace("-", " ").replace("_", " ").title()

            path = self.kernel.remember(
                title=title,
                content=content,
                memory_type=MemoryType(memory_type),
                tags=tags or [],
                salience=salience,
            )

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Imported '{import_path.name}' as memory: {title}",
                    "path": path,
                }
            )

        except Exception as e:
            logger.error(f"Error importing document: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def delete_memory(self, memory_id: str) -> dict[str, Any]:
        """Delete a memory from the vault.

        Args:
            memory_id: ID of the memory to delete

        Returns:
            Dictionary with deletion result
        """
        try:
            self._check_server_health()
            if self.readonly:
                return self._readonly_refusal("delete_memory")
            # Find the memory file using graph lookup (much faster than rglob)
            node = self.kernel.graph.get(memory_id)
            if not node or not node.source_path:
                return self._add_vault_context(
                    {
                        "success": False,
                        "error": f"Memory not found: {memory_id}",
                    }
                )

            memory_path = Path(node.source_path)
            if not memory_path.exists():
                return self._add_vault_context(
                    {
                        "success": False,
                        "error": f"Memory file not found: {memory_path}",
                    }
                )

            # Get memory info before deletion
            title = node.title if node else memory_id

            # Delete the file
            memory_path.unlink()

            # Remove from graph and re-ingest to keep indexes consistent
            self.kernel.graph.remove_node(memory_id)

            logger.info(f"Deleted memory: {memory_id}")

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Deleted memory: {title}",
                    "memory_id": memory_id,
                }
            )

        except Exception as e:
            logger.error(f"Error deleting memory: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def update_memory(
        self,
        memory_id: str,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        salience: float | None = None,
        append_content: bool = False,
    ) -> dict[str, Any]:
        """Update an existing memory.

        Args:
            memory_id: ID of the memory to update
            title: New title (optional)
            content: New content (optional)
            tags: New tags - replaces existing (optional)
            salience: New salience score (optional)
            append_content: If True, append content instead of replacing

        Returns:
            Dictionary with update result
        """
        try:
            if self.readonly:
                return self._readonly_refusal("update_memory")
            self._check_server_health()
            import re
            from datetime import datetime, timezone

            import yaml

            # Find the memory file using graph lookup (much faster than rglob)
            node = self.kernel.graph.get(memory_id)
            if not node or not node.source_path:
                return {
                    "success": False,
                    "error": f"Memory not found: {memory_id}",
                }

            memory_path = Path(node.source_path)
            if not memory_path.exists():
                return {
                    "success": False,
                    "error": f"Memory file not found: {memory_path}",
                }

            # Read existing content
            file_content = memory_path.read_text(encoding="utf-8")

            # Parse frontmatter
            if file_content.startswith("---\n"):
                parts = file_content.split("---\n", 2)
                if len(parts) >= 3:
                    frontmatter_str = parts[1]
                    body = parts[2].strip()
                    frontmatter = yaml.safe_load(frontmatter_str)
                else:
                    return {"success": False, "error": "Invalid frontmatter format"}
            else:
                return {"success": False, "error": "No frontmatter found"}

            # Update frontmatter
            if title:
                frontmatter["title"] = title
            if salience is not None:
                if not 0.0 <= salience <= 1.0:
                    return {
                        "success": False,
                        "error": "Salience must be between 0.0 and 1.0",
                    }
                frontmatter["salience"] = salience
            frontmatter["modified"] = datetime.now(timezone.utc).isoformat()

            # Update content
            if content:
                # Remove old tags from body first
                body = re.sub(r"\n\n#[\w\s#]+$", "", body).strip()
                body = f"{body}\n\n{content}" if append_content else content

            # Update tags
            if tags:
                # Remove old tag line
                body = re.sub(r"\n\n#[\w\s#]+$", "", body).strip()
                tags_line = " ".join(f"#{tag}" for tag in tags)
                body = f"{body}\n\n{tags_line}"

            # Write back
            new_frontmatter = (
                "---\n"
                + yaml.safe_dump(frontmatter, sort_keys=False).strip()
                + "\n---\n\n"
            )
            self._atomic_write(memory_path, new_frontmatter + body + "\n")

            logger.info(f"Updated memory: {memory_id}")

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Updated memory: {frontmatter['title']}",
                    "memory_id": memory_id,
                }
            )

        except Exception as e:
            logger.error(f"Error updating memory: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def suggest_tags(
        self,
        content: str,
        title: str = "",
        existing_tags: list[str] | None = None,
        min_confidence: float = 0.3,
        max_suggestions: int = 5,
    ) -> dict[str, Any]:
        """Suggest tags for a note using AI analysis.

        Args:
            content: Note content to analyze
            title: Note title (optional)
            existing_tags: Tags already assigned (optional)
            min_confidence: Minimum confidence score (0.0-1.0)
            max_suggestions: Maximum number of suggestions

        Returns:
            Dictionary with tag suggestions
        """
        try:
            self._check_server_health()
            from ..ai.auto_tagger import AutoTagger

            tagger = AutoTagger(
                self.kernel,
                min_confidence=min_confidence,
                max_suggestions=max_suggestions,
            )

            suggestions = await tagger.suggest_tags(
                content=content,
                title=title,
                existing_tags=existing_tags or [],
            )

            formatted_suggestions = [
                {
                    "tag": s.tag,
                    "confidence": round(s.confidence, 3),
                    "reason": s.reason,
                    "source": s.source,
                }
                for s in suggestions
            ]

            return self._add_vault_context(
                {
                    "success": True,
                    "count": len(formatted_suggestions),
                    "suggestions": formatted_suggestions,
                }
            )

        except Exception as e:
            logger.error(f"Error suggesting tags: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def suggest_links(
        self,
        content: str,
        title: str = "",
        note_id: str | None = None,
        existing_links: list[str] | None = None,
        min_confidence: float = 0.4,
        max_suggestions: int = 10,
    ) -> dict[str, Any]:
        """Suggest wikilinks for a note using semantic similarity and graph analysis.

        Args:
            content: Note content to analyze
            title: Note title (optional)
            note_id: Note ID for graph-based suggestions (optional)
            existing_links: Links already in the note (optional)
            min_confidence: Minimum confidence score (0.0-1.0)
            max_suggestions: Maximum number of suggestions

        Returns:
            Dictionary with link suggestions
        """
        try:
            self._check_server_health()
            from ..ai.link_suggester import LinkSuggester

            suggester = LinkSuggester(
                self.kernel,
                min_confidence=min_confidence,
                max_suggestions=max_suggestions,
            )

            suggestions = await suggester.suggest_links(
                content=content,
                title=title,
                note_id=note_id,
                existing_links=existing_links or [],
            )

            formatted_suggestions = [
                {
                    "target_title": s.target_title,
                    "target_id": s.target_id,
                    "confidence": round(s.confidence, 3),
                    "reason": s.reason,
                    "source": s.source,
                    "bidirectional": s.bidirectional,
                }
                for s in suggestions
            ]

            return self._add_vault_context(
                {
                    "success": True,
                    "count": len(formatted_suggestions),
                    "suggestions": formatted_suggestions,
                }
            )

        except Exception as e:
            logger.error(f"Error suggesting links: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def detect_knowledge_gaps(
        self,
        min_severity: float = 0.3,
        max_gaps: int = 20,
        gap_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Detect knowledge gaps in the vault.

        Args:
            min_severity: Minimum severity threshold (0.0-1.0)
            max_gaps: Maximum number of gaps to return
            gap_types: Specific gap types to detect (optional):
                      ['missing_topic', 'weak_coverage', 'isolated_note', 'missing_link']

        Returns:
            Dictionary with detected gaps
        """
        try:
            self._check_server_health()
            from ..ai.gap_detector import GapDetector

            detector = GapDetector(
                self.kernel,
                min_severity=min_severity,
                max_gaps=max_gaps,
            )

            gaps = await detector.detect_gaps()

            # Filter by gap types if specified
            if gap_types:
                gaps = [g for g in gaps if g.gap_type in gap_types]

            formatted_gaps = [
                {
                    "type": g.gap_type,
                    "title": g.title,
                    "description": g.description,
                    "severity": round(g.severity, 2),
                    "suggestions": g.suggestions,
                    "related_notes": g.related_notes[:5],  # Limit to 5
                }
                for g in gaps
            ]

            return self._add_vault_context(
                {
                    "success": True,
                    "count": len(formatted_gaps),
                    "gaps": formatted_gaps,
                    "summary": {
                        "total_gaps": len(formatted_gaps),
                        "by_type": {
                            gap_type: len([g for g in gaps if g.gap_type == gap_type])
                            for gap_type in [
                                "missing_topic",
                                "weak_coverage",
                                "isolated_note",
                                "missing_link",
                            ]
                        },
                        "avg_severity": sum(g.severity for g in gaps) / len(gaps)
                        if gaps
                        else 0.0,
                    },
                }
            )

        except Exception as e:
            logger.error(f"Error detecting knowledge gaps: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def analyze_knowledge_base(
        self,
        include_gaps: bool = True,
        include_clusters: bool = True,
        include_paths: bool = True,
    ) -> dict[str, Any]:
        """Perform comprehensive knowledge base analysis.

        Args:
            include_gaps: Include gap detection
            include_clusters: Include topic clustering
            include_paths: Include learning path suggestions

        Returns:
            Dictionary with comprehensive analysis
        """
        try:
            self._check_server_health()
            from ..ai.gap_detector import GapDetector

            detector = GapDetector(self.kernel)
            analysis = await detector.analyze_knowledge_base()

            # Filter based on requested components
            if not include_gaps:
                analysis["gaps"] = []
                analysis["summary"]["total_gaps"] = 0
            if not include_clusters:
                analysis["clusters"] = []
                analysis["summary"]["total_clusters"] = 0
            if not include_paths:
                analysis["learning_paths"] = []
                analysis["summary"]["total_paths"] = 0

            return self._add_vault_context(
                {
                    "success": True,
                    "analysis": analysis,
                }
            )

        except Exception as e:
            logger.error(f"Error analyzing knowledge base: {e}")
            return self._add_vault_context(
                {
                    "success": False,
                    "error": str(e),
                }
            )

    async def list_available_tools(self) -> dict[str, Any]:
        """List all available MCP tools with descriptions.

        Returns:
            Dictionary with list of available tools
        """
        try:
            tools_info = []
            for tool in self.get_tools_schema():
                tools_info.append(
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "required_params": tool["inputSchema"].get("required", []),
                    }
                )

            return {
                "success": True,
                "total_tools": len(tools_info),
                "tools": tools_info,
                "categories": {
                    "search": ["search_vault", "query_with_context"],
                    "create": ["create_memory", "import_document"],
                    "read": ["get_memory", "list_memories"],
                    "update": ["update_memory"],
                    "delete": ["delete_memory"],
                    "analytics": ["get_vault_info", "get_vault_stats"],
                    "discovery": ["list_available_tools"],
                    "autonomous": [
                        "auto_hook_turn",
                        "auto_hook_query",
                        "auto_hook_response",
                        "configure_autonomous_mode",
                        "configure_capture_mode",
                        "get_autonomous_config",
                        "get_capture_mode",
                    ],
                    "graph": [
                        "relate_memories",
                        "search_by_graph",
                        "find_path",
                    ],
                    "bulk": ["bulk_create"],
                    "ai": [
                        "suggest_tags",
                        "suggest_links",
                        "detect_knowledge_gaps",
                        "analyze_knowledge_base",
                    ],
                },
            }
        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    # ==================== Graph-Native Tools ====================

    async def relate_memories(
        self,
        source_id: str,
        target_id: str,
        relationship: str | None = None,
    ) -> dict[str, Any]:
        """Create a wikilink connection between two memories.

        Args:
            source_id: ID of the source memory
            target_id: ID of the target memory to link to
            relationship: Optional description of the relationship

        Returns:
            Dictionary with result
        """
        try:
            self._check_server_health()
            if self.readonly:
                return self._readonly_refusal("relate_memories")
            import re

            source_node = self.kernel.graph.get(source_id)
            if not source_node:
                return self._add_vault_context(
                    {"success": False, "error": f"Source memory not found: {source_id}"}
                )

            target_node = self.kernel.graph.get(target_id)
            if not target_node:
                return self._add_vault_context(
                    {"success": False, "error": f"Target memory not found: {target_id}"}
                )

            # Check if link already exists
            if target_id in source_node.links:
                return self._add_vault_context(
                    {
                        "success": True,
                        "message": f"Link already exists: {source_id} -> {target_id}",
                        "already_linked": True,
                    }
                )

            # Read the source file and append wikilink
            source_path = Path(source_node.source_path)
            content = source_path.read_text(encoding="utf-8")

            link_text = f"[[{target_id}]]"
            if relationship:
                link_text = f"{relationship}: [[{target_id}]]"

            # Append the link before the tag line (if any) or at the end
            tag_pattern = r"\n\n#[\w\s#]+$"
            tag_match = re.search(tag_pattern, content)
            if tag_match:
                insert_pos = tag_match.start()
                content = (
                    content[:insert_pos] + f"\n\n{link_text}" + content[insert_pos:]
                )
            else:
                content = content.rstrip() + f"\n\n{link_text}\n"

            self._atomic_write(source_path, content)

            # Update graph incrementally instead of full rebuild (much faster)
            source_node = self.kernel.graph.get(source_id)
            if source_node:
                # Update in-memory graph
                if target_id not in source_node.links:
                    source_node.links.append(target_id)

                # Rebuild backlinks (fast operation)
                self.kernel.graph.build_backlinks()

                logger.debug(
                    f"Updated graph incrementally for link: {source_id} -> {target_id}"
                )

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Linked '{source_node.title}' -> '{target_node.title}'",
                    "source": source_id,
                    "target": target_id,
                }
            )

        except Exception as e:
            logger.error(f"Error relating memories: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def search_by_graph(
        self,
        memory_id: str,
        depth: int = 2,
        include_backlinks: bool = True,
    ) -> dict[str, Any]:
        """Traverse the graph from a memory to find connected memories.

        Args:
            memory_id: Starting memory ID
            depth: How many hops to traverse
            include_backlinks: Whether to follow backlinks

        Returns:
            Dictionary with connected nodes and their relationships
        """
        try:
            self._check_server_health()
            node = self.kernel.graph.get(memory_id)
            if not node:
                return self._add_vault_context(
                    {"success": False, "error": f"Memory not found: {memory_id}"}
                )

            neighbors = self.kernel.graph.neighbors(
                memory_id, depth=depth, include_backlinks=include_backlinks
            )

            formatted = [
                {
                    "id": n.id,
                    "title": n.title,
                    "memory_type": n.memory_type.value,
                    "tags": n.tags,
                    "salience": n.salience,
                    "links_to": [
                        lid
                        for lid in n.links
                        if lid in {nb.id for nb in neighbors} or lid == memory_id
                    ],
                    "preview": n.content[:200],
                }
                for n in neighbors
            ]

            return self._add_vault_context(
                {
                    "success": True,
                    "center": {
                        "id": node.id,
                        "title": node.title,
                        "links": node.links,
                        "backlinks": node.backlinks,
                    },
                    "connected_count": len(formatted),
                    "depth": depth,
                    "connected": formatted,
                }
            )

        except Exception as e:
            logger.error(f"Error in graph search: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def find_path(
        self,
        from_id: str,
        to_id: str,
    ) -> dict[str, Any]:
        """Find the shortest path between two memories in the graph.

        Args:
            from_id: Starting memory ID
            to_id: Target memory ID

        Returns:
            Dictionary with the path or message if no path exists
        """
        try:
            self._check_server_health()
            path = self.kernel.graph.find_path(from_id, to_id)

            if path is None:
                return self._add_vault_context(
                    {
                        "success": True,
                        "path_found": False,
                        "message": f"No path found between '{from_id}' and '{to_id}'",
                    }
                )

            formatted_path = [
                {
                    "id": node.id,
                    "title": node.title,
                    "memory_type": node.memory_type.value,
                }
                for node in path
            ]

            return self._add_vault_context(
                {
                    "success": True,
                    "path_found": True,
                    "path_length": len(path),
                    "path": formatted_path,
                }
            )

        except Exception as e:
            logger.error(f"Error finding path: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def bulk_create(
        self,
        memories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create multiple memories in one operation.

        Args:
            memories: List of memory dicts, each with title, content,
                      and optionally memory_type, tags, salience

        Returns:
            Dictionary with creation results
        """
        try:
            self._check_server_health()
            if self.readonly:
                return self._readonly_refusal("bulk_create")
            results, errors = self.kernel.remember_many(
                memories=memories, continue_on_error=True
            )

            return self._add_vault_context(
                {
                    "success": True,
                    "created": len(results),
                    "failed": len(errors),
                    "paths": results,
                    "errors": [
                        {"memory": str(mem.get("title", "unknown")), "error": str(err)}
                        for mem, err in errors
                    ]
                    if errors
                    else [],
                }
            )

        except Exception as e:
            logger.error(f"Error in bulk create: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def batch_update(
        self,
        updates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Update multiple memories in one operation.

        Args:
            updates: List of update dicts with 'memory_id' and fields to update

        Returns:
            Dictionary with update results
        """
        try:
            self._check_server_health()
            if self.readonly:
                return self._readonly_refusal("batch_update")

            # Convert to format expected by kernel.update_many
            update_tuples = [
                (upd["memory_id"], {k: v for k, v in upd.items() if k != "memory_id"})
                for upd in updates
            ]

            updated_ids, errors = self.kernel.update_many(
                update_tuples, continue_on_error=True
            )

            return self._add_vault_context(
                {
                    "success": True,
                    "updated": len(updated_ids),
                    "failed": len(errors),
                    "updated_ids": updated_ids,
                    "errors": [
                        {"memory_id": str(mid), "error": str(err)}
                        for mid, err in errors
                    ]
                    if errors
                    else [],
                }
            )

        except Exception as e:
            logger.error(f"Error in batch update: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def batch_delete(
        self,
        memory_ids: list[str],
    ) -> dict[str, Any]:
        """Delete multiple memories in one operation.

        Args:
            memory_ids: List of memory IDs to delete

        Returns:
            Dictionary with deletion results
        """
        try:
            self._check_server_health()
            if self.readonly:
                return self._readonly_refusal("batch_delete")

            deleted_ids = []
            errors = []

            for memory_id in memory_ids:
                try:
                    node = self.kernel.graph.get(memory_id)
                    if not node or not node.source_path:
                        errors.append((memory_id, "Memory not found"))
                        continue

                    memory_path = Path(node.source_path)
                    if not memory_path.exists():
                        errors.append((memory_id, "File not found"))
                        continue

                    memory_path.unlink()
                    self.kernel.graph.remove_node(memory_id)
                    deleted_ids.append(memory_id)

                except Exception as e:
                    errors.append((memory_id, str(e)))

            # Re-ingest if any successful deletions
            if deleted_ids:
                self.kernel.ingest(force=False)

            return self._add_vault_context(
                {
                    "success": True,
                    "deleted": len(deleted_ids),
                    "failed": len(errors),
                    "deleted_ids": deleted_ids,
                    "errors": [
                        {"memory_id": str(mid), "error": str(err)}
                        for mid, err in errors
                    ]
                    if errors
                    else [],
                }
            )

        except Exception as e:
            logger.error(f"Error in batch delete: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def export_vault_tool(
        self,
        output_path: str,
        format: str = "json",
        filter_tags: list[str] | None = None,
        compress: bool = False,
    ) -> dict[str, Any]:
        """Export vault memories to specified format.

        Args:
            output_path: Path for the export file
            format: Export format - 'json', 'csv', or 'zip'
            filter_tags: Optional list of tags to filter memories
            compress: Whether to compress the output

        Returns:
            Dictionary with export result
        """
        try:
            self._check_server_health()

            path = self.kernel.export_vault(
                output_path=output_path,
                format=format,  # type: ignore
                filter_tags=filter_tags,
                compress=compress,
            )

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Exported vault to {format} format",
                    "path": str(path),
                    "format": format,
                }
            )

        except Exception as e:
            logger.error(f"Error exporting vault: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def import_backup_tool(
        self,
        backup_path: str,
        merge: bool = True,
        skip_duplicates: bool = False,
    ) -> dict[str, Any]:
        """Import memories from a backup file.

        Args:
            backup_path: Path to backup file
            merge: If True, merge with existing. If False, clear vault first.
            skip_duplicates: If True, skip memories that already exist

        Returns:
            Dictionary with import result
        """
        try:
            self._check_server_health()
            if self.readonly:
                return self._readonly_refusal("import_backup_tool")

            stats = self.kernel.import_backup(
                backup_path=backup_path,
                merge=merge,
                skip_duplicates=skip_duplicates,
            )

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Imported {stats['imported']} memories",
                    "imported": stats["imported"],
                    "skipped": stats["skipped"],
                    "failed": stats["failed"],
                }
            )

        except Exception as e:
            logger.error(f"Error importing backup: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def create_backup_tool(
        self,
        destination: str,
        compress: bool = True,
    ) -> dict[str, Any]:
        """Create a backup of the vault.

        Args:
            destination: Destination directory or file path
            compress: Whether to create compressed ZIP backup

        Returns:
            Dictionary with backup result
        """
        try:
            self._check_server_health()

            path = self.kernel.create_backup(
                destination=destination,
                compress=compress,
            )

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Backup created at {path}",
                    "path": str(path),
                    "compressed": compress,
                }
            )

        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    # ==================== Config Management Methods ====================

    async def get_config_value(self, key: str) -> dict[str, Any]:
        """Get a configuration value.

        Args:
            key: Configuration key

        Returns:
            Dictionary with configuration value
        """
        try:
            from ..core.config import MemographConfig

            config = MemographConfig()
            value = config.get(key)

            return self._add_vault_context(
                {
                    "success": True,
                    "key": key,
                    "value": value,
                }
            )

        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def set_config_value(self, key: str, value: Any) -> dict[str, Any]:
        """Set a configuration value.

        Args:
            key: Configuration key
            value: Value to set

        Returns:
            Dictionary with result
        """
        try:
            from ..core.config import MemographConfig

            config = MemographConfig()
            config.set(key, value)

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Set {key} = {value}",
                    "key": key,
                    "value": value,
                }
            )

        except Exception as e:
            logger.error(f"Error setting config: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def list_config_all(self) -> dict[str, Any]:
        """List all configuration settings.

        Returns:
            Dictionary with all configuration
        """
        try:
            from ..core.config import MemographConfig

            config = MemographConfig()
            all_config = config.list_all()

            return self._add_vault_context(
                {
                    "success": True,
                    "config": all_config,
                    "active_profile": config.get_active_profile(),
                }
            )

        except Exception as e:
            logger.error(f"Error listing config: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def create_profile_config(
        self, name: str, settings: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a configuration profile.

        Args:
            name: Profile name
            settings: Profile settings

        Returns:
            Dictionary with result
        """
        try:
            from ..core.config import MemographConfig

            config = MemographConfig()
            config.create_profile(name, settings)

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Created profile: {name}",
                    "profile": name,
                }
            )

        except Exception as e:
            logger.error(f"Error creating profile: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def use_profile_config(self, name: str) -> dict[str, Any]:
        """Switch to a configuration profile.

        Args:
            name: Profile name

        Returns:
            Dictionary with result
        """
        try:
            from ..core.config import MemographConfig

            config = MemographConfig()
            config.use_profile(name)

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Switched to profile: {name}",
                    "active_profile": name,
                }
            )

        except Exception as e:
            logger.error(f"Error switching profile: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def list_profiles_config(self) -> dict[str, Any]:
        """List all configuration profiles.

        Returns:
            Dictionary with profiles list
        """
        try:
            from ..core.config import MemographConfig

            config = MemographConfig()
            profiles = config.list_profiles()
            active = config.get_active_profile()

            return self._add_vault_context(
                {
                    "success": True,
                    "profiles": profiles,
                    "active_profile": active,
                }
            )

        except Exception as e:
            logger.error(f"Error listing profiles: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    async def delete_profile_config(self, name: str) -> dict[str, Any]:
        """Delete a configuration profile.

        Args:
            name: Profile name

        Returns:
            Dictionary with result
        """
        try:
            from ..core.config import MemographConfig

            config = MemographConfig()
            deleted = config.delete_profile(name)

            if deleted:
                return self._add_vault_context(
                    {
                        "success": True,
                        "message": f"Deleted profile: {name}",
                    }
                )
            else:
                return self._add_vault_context(
                    {
                        "success": False,
                        "error": f"Profile not found: {name}",
                    }
                )

        except Exception as e:
            logger.error(f"Error deleting profile: {e}")
            return self._add_vault_context({"success": False, "error": str(e)})

    # ==================== Autonomous Hooks Methods ====================

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
        return await self.autonomous_hooks.auto_hook_query(
            user_query=user_query,
            conversation_id=conversation_id,
            auto_search=auto_search,
            auto_save_query=auto_save_query,
        )

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
        return await self.autonomous_hooks.auto_hook_response(
            user_query=user_query,
            ai_response=ai_response,
            sources_used=sources_used,
            conversation_id=conversation_id,
            auto_save=auto_save,
        )

    async def configure_autonomous_mode(
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
        return await self.autonomous_hooks.configure(
            auto_search=auto_search,
            auto_save_queries=auto_save_queries,
            auto_save_responses=auto_save_responses,
            min_query_length=min_query_length,
        )

    async def get_autonomous_config(self) -> dict[str, Any]:
        """Get current autonomous hooks configuration.

        Returns:
            Dictionary with current settings and recommendations
        """
        return self.autonomous_hooks.get_configuration()

    async def auto_hook_turn(
        self,
        user_query: str,
        ai_response: str,
        sources_used: list[dict[str, Any]] | None = None,
        conversation_id: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Unified end-of-turn hook combining search-context recall and save.

        This is the recommended Tier-B entry point for MCP clients (Claude
        Desktop, Cursor, Cline, Codex, ChatGPT, Gemini). One call per turn
        replaces the auto_hook_query + auto_hook_response pair, halving the
        failure surface from forgotten calls.

        Args:
            user_query: The user's verbatim message for this turn.
            ai_response: The assistant's complete reply.
            sources_used: Optional sources cited from the vault.
            conversation_id: Optional stable conversation identifier.
            mode: One-call override of the server-configured capture mode
                ('low', 'mid', 'high'). Unknown values fall back to default.

        Returns:
            Dictionary with the capture decision and save result (if any).
        """
        return await self.autonomous_hooks.auto_hook_turn(
            user_query=user_query,
            ai_response=ai_response,
            sources_used=sources_used,
            conversation_id=conversation_id,
            mode=mode,
        )

    async def configure_capture_mode(self, mode: str) -> dict[str, Any]:
        """Switch the capture mode at runtime.

        Args:
            mode: 'low' (search only), 'mid' (filtered save — default),
                or 'high' (save every substantive turn).

        Returns:
            Dictionary with the new mode and a summary of behavior.
        """
        normalized = normalize_mode(mode)
        if mode and normalized != mode.strip().lower():
            return {
                "success": False,
                "error": (
                    f"Unknown capture mode {mode!r}. "
                    f"Valid modes: {', '.join(VALID_MODES)}."
                ),
                "current_mode": self.capture_mode,
            }
        self.capture_mode = normalized
        logger.info(f"Capture mode switched to: {self.capture_mode}")
        return {
            "success": True,
            "mode": self.capture_mode,
            "message": f"Capture mode set to {self.capture_mode!r}.",
            "behavior": {
                "low": "Search-only. No saves to the vault.",
                "mid": "Filtered save (default). Skips noise/trivial turns.",
                "high": "Save every substantive turn verbatim.",
            }[self.capture_mode],
        }

    async def get_capture_mode(self) -> dict[str, Any]:
        """Report the current capture mode and what each mode does."""
        return {
            "success": True,
            "current_mode": self.capture_mode,
            "valid_modes": list(VALID_MODES),
            "descriptions": {
                "low": "Search-only. No saves to the vault.",
                "mid": "Filtered save (default). Skips noise/trivial turns.",
                "high": "Save every substantive turn verbatim.",
            },
            "env_var": "MEMOGRAPH_CAPTURE_MODE",
        }

    async def verify_last_save(
        self,
        time_window_seconds: int = 60,
        conversation_only: bool = True,
    ) -> dict[str, Any]:
        """Verify if a recent conversation was saved.

        Args:
            time_window_seconds: How far back to check in seconds
            conversation_only: Only check conversation memories

        Returns:
            Dictionary with verification result
        """
        return await self.autonomous_hooks.verify_last_save(
            time_window_seconds=time_window_seconds,
            conversation_only=conversation_only,
        )

    async def get_save_stats(self, period: str = "session") -> dict[str, Any]:
        """Get statistics about save success rate.

        Args:
            period: Time period to analyze ('session', 'hour', 'day', 'week', 'all')

        Returns:
            Dictionary with save statistics
        """
        return await self.autonomous_hooks.get_save_stats(period=period)

    async def get_auto_save_analytics(
        self, period: str = "day", include_recommendations: bool = True
    ) -> dict[str, Any]:
        """Get comprehensive auto-save analytics.

        Args:
            period: 'hour', 'day', 'week', or 'all'
            include_recommendations: Whether to include recommendations

        Returns:
            Analytics dictionary
        """
        return await self.autonomous_hooks.get_auto_save_analytics(
            period, include_recommendations
        )

    async def get_monitor_status(self) -> dict[str, Any]:
        """Get status of the conversation monitor (Layer 2).

        Returns:
            Dictionary with monitor status and diagnostics
        """
        try:
            if not self.conversation_monitor:
                return {
                    "success": True,
                    "monitor_enabled": False,
                    "message": "Conversation monitor (Layer 2) is not enabled. Set MEMOGRAPH_AUTO_SAVE_MONITOR=true to enable.",
                    "recommendation": "Layer 2 provides backup auto-save for missed conversations. Enable it for better coverage.",
                }

            stats = self.conversation_monitor.get_stats()

            # Check if monitor is actually detecting activity
            has_activity = stats.get("last_activity") is not None
            is_detecting = stats.get("total_detected", 0) > 0

            status = "active" if has_activity and is_detecting else "idle"
            if not has_activity:
                status = "inactive"

            return {
                "success": True,
                "monitor_enabled": True,
                "status": status,
                "statistics": stats,
                "diagnostics": {
                    "background_loop_running": True,  # If we got here, it's running
                    "detecting_conversations": is_detecting,
                    "has_recent_activity": has_activity,
                },
                "message": f"Monitor is {status}. Detected {stats.get('total_detected', 0)} conversations, saved {stats.get('saved', 0)}.",
            }

        except Exception as e:
            logger.error(f"Error getting monitor status: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def start_monitor(self) -> None:
        """Start the conversation monitor background task.

        This must be called from an async context after __init__.
        """
        if self.conversation_monitor and not self._monitor_task:
            self._monitor_task = asyncio.create_task(
                self.conversation_monitor.monitor_loop()
            )
            logger.info("✅ Conversation monitor background task started")

    async def stop_monitor(self) -> None:
        """Stop the conversation monitor gracefully."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            logger.info("Conversation monitor stopped")

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """Get MCP tools schema for registration.

        Returns:
            List of tool schemas
        """
        return [
            {
                "name": "search_vault",
                "description": "Search memories in the MemoGraph vault using semantic or keyword search",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query string",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tags to filter by",
                        },
                        "top_k": {
                            "type": "number",
                            "description": "Maximum number of results (default: 8)",
                            "default": 8,
                        },
                        "memory_type": {
                            "type": "string",
                            "enum": ["episodic", "semantic", "procedural", "fact"],
                            "description": "Optional memory type filter",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "create_memory",
                "description": "Create a new memory in the MemoGraph vault",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Memory title",
                        },
                        "content": {
                            "type": "string",
                            "description": "Memory content",
                        },
                        "memory_type": {
                            "type": "string",
                            "enum": ["episodic", "semantic", "procedural", "fact"],
                            "description": "Type of memory",
                            "default": "semantic",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tags",
                        },
                        "salience": {
                            "type": "number",
                            "description": "Importance score 0.0-1.0",
                            "default": 0.7,
                        },
                    },
                    "required": ["title", "content"],
                },
            },
            {
                "name": "query_with_context",
                "description": "Retrieve relevant context from the vault for a question. If LLM provider is configured, can optionally generate an answer. Otherwise, returns context for the client's LLM to use.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Question to ask",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tag filter",
                        },
                        "top_k": {
                            "type": "number",
                            "description": "Number of memories to use as context",
                            "default": 8,
                        },
                        "generate_answer": {
                            "type": "boolean",
                            "description": "If true and LLM configured, generate answer. If false, return context only.",
                            "default": True,
                        },
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "get_vault_info",
                "description": "Get information about the currently configured MemoGraph vault (path, name, configuration). Use this when you need to know which vault is being used.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "get_vault_stats",
                "description": "Get statistics about the currently configured MemoGraph vault (memory counts, types, tags)",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "list_memories",
                "description": "List memories with optional filters",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "number",
                            "description": "Maximum number to return",
                            "default": 20,
                        },
                        "memory_type": {
                            "type": "string",
                            "enum": ["episodic", "semantic", "procedural", "fact"],
                            "description": "Filter by type",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by tags",
                        },
                        "sort_by": {
                            "type": "string",
                            "enum": ["created", "salience", "title"],
                            "description": "Sort by field",
                            "default": "created",
                        },
                    },
                },
            },
            {
                "name": "get_memory",
                "description": "Get full content of a specific memory by ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {
                            "type": "string",
                            "description": "Memory ID",
                        },
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "import_document",
                "description": "Import a document (TXT, PDF, DOCX) into the vault",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to document",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tags",
                        },
                        "memory_type": {
                            "type": "string",
                            "enum": ["episodic", "semantic", "procedural", "fact"],
                            "default": "episodic",
                        },
                        "salience": {
                            "type": "number",
                            "default": 0.7,
                        },
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "delete_memory",
                "description": "Delete a memory from the vault by ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {
                            "type": "string",
                            "description": "Memory ID to delete",
                        },
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "update_memory",
                "description": "Update an existing memory's title, content, tags, or salience",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {
                            "type": "string",
                            "description": "Memory ID to update",
                        },
                        "title": {
                            "type": "string",
                            "description": "New title (optional)",
                        },
                        "content": {
                            "type": "string",
                            "description": "New content (optional)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "New tags - replaces existing (optional)",
                        },
                        "salience": {
                            "type": "number",
                            "description": "New salience score (0.0-1.0)",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "append_content": {
                            "type": "boolean",
                            "description": "If true, append content instead of replacing",
                            "default": False,
                        },
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "batch_update",
                "description": "Update multiple memories in one efficient operation. Much faster than calling update_memory multiple times.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "updates": {
                            "type": "array",
                            "description": "List of update objects",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "memory_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "content": {"type": "string"},
                                    "tags": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "salience": {"type": "number"},
                                },
                                "required": ["memory_id"],
                            },
                        },
                    },
                    "required": ["updates"],
                },
            },
            {
                "name": "batch_delete",
                "description": "Delete multiple memories in one efficient operation. Much faster than calling delete_memory multiple times.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_ids": {
                            "type": "array",
                            "description": "List of memory IDs to delete",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["memory_ids"],
                },
            },
            {
                "name": "export_vault_tool",
                "description": "Export vault memories to JSON, CSV, or ZIP format. Useful for backups, data portability, and integration with external tools.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "output_path": {
                            "type": "string",
                            "description": "Path for the export file",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["json", "csv", "zip"],
                            "description": "Export format",
                            "default": "json",
                        },
                        "filter_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of tags to filter memories",
                        },
                        "compress": {
                            "type": "boolean",
                            "description": "Whether to compress the output (gzip for json/csv)",
                            "default": False,
                        },
                    },
                    "required": ["output_path"],
                },
            },
            {
                "name": "import_backup_tool",
                "description": "Import memories from a backup file (JSON or ZIP). Useful for restoring from backups or migrating vaults.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "backup_path": {
                            "type": "string",
                            "description": "Path to backup file",
                        },
                        "merge": {
                            "type": "boolean",
                            "description": "If true, merge with existing. If false, clear vault first.",
                            "default": True,
                        },
                        "skip_duplicates": {
                            "type": "boolean",
                            "description": "If true, skip memories that already exist",
                            "default": False,
                        },
                    },
                    "required": ["backup_path"],
                },
            },
            {
                "name": "create_backup_tool",
                "description": "Create a backup of the vault. Essential for disaster recovery and version control.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "destination": {
                            "type": "string",
                            "description": "Destination directory or file path",
                        },
                        "compress": {
                            "type": "boolean",
                            "description": "Whether to create compressed ZIP backup",
                            "default": True,
                        },
                    },
                    "required": ["destination"],
                },
            },
            {
                "name": "get_config_value",
                "description": "Get a configuration value from ~/.memograph/config.yaml",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Configuration key to get",
                        },
                    },
                    "required": ["key"],
                },
            },
            {
                "name": "set_config_value",
                "description": "Set a configuration value in ~/.memograph/config.yaml",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Configuration key to set",
                        },
                        "value": {
                            "description": "Value to set (can be any type)",
                        },
                    },
                    "required": ["key", "value"],
                },
            },
            {
                "name": "list_config_all",
                "description": "List all configuration settings from ~/.memograph/config.yaml",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "create_profile_config",
                "description": "Create a new configuration profile with custom settings",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Profile name",
                        },
                        "settings": {
                            "type": "object",
                            "description": "Profile settings dictionary",
                        },
                    },
                    "required": ["name", "settings"],
                },
            },
            {
                "name": "use_profile_config",
                "description": "Switch to a specific configuration profile",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Profile name to activate",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "list_profiles_config",
                "description": "List all available configuration profiles",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "delete_profile_config",
                "description": "Delete a configuration profile",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Profile name to delete",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "list_available_tools",
                "description": "List all available MCP tools with their descriptions and categories",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "auto_hook_query",
                "description": (
                    "🔍 AUTO-SEARCH VAULT - Call at the START of a conversation to search for relevant context.\n\n"
                    "⚠️ NOTE: Usually it's better to just use 'search_vault' or 'query_with_context' directly.\n\n"
                    "This tool:\n"
                    "1. Searches the vault for relevant memories\n"
                    "2. Optionally saves the query itself (usually disabled)\n"
                    "3. Returns context and sources\n\n"
                    "Most users don't need this - use 'search_vault' instead."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_query": {
                            "type": "string",
                            "description": "The user's query/question",
                        },
                        "conversation_id": {
                            "type": "string",
                            "description": "Optional conversation ID for tracking (optional)",
                        },
                        "auto_search": {
                            "type": "boolean",
                            "description": "Override auto_search setting (optional)",
                        },
                        "auto_save_query": {
                            "type": "boolean",
                            "description": "Override auto_save_queries setting (optional)",
                        },
                    },
                    "required": ["user_query"],
                },
            },
            {
                "name": "auto_hook_response",
                "description": (
                    "💾 SAVE CONVERSATION - Call this IMMEDIATELY after answering to save our exchange.\n\n"
                    "⚠️ IMPORTANT: This tool is NOT automatic - you must explicitly call it after each meaningful exchange.\n\n"
                    "✅ WHEN TO CALL:\n"
                    "- After answering questions\n"
                    "- After providing insights or advice\n"
                    "- After planning or decision-making conversations\n"
                    "- After any exchange worth remembering\n\n"
                    "❌ SKIP FOR:\n"
                    "- Simple greetings ('hi', 'hello')\n"
                    "- Acknowledgments ('ok', 'thanks')\n"
                    "- Clarification questions\n\n"
                    "📝 USAGE:\n"
                    "auto_hook_response(\n"
                    "    user_query='User's question here',\n"
                    "    ai_response='Your complete answer here'\n"
                    ")\n\n"
                    "This builds conversation history for future reference."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_query": {
                            "type": "string",
                            "description": "Original user query",
                        },
                        "ai_response": {
                            "type": "string",
                            "description": "AI's response to the query",
                        },
                        "sources_used": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "title": {"type": "string"},
                                },
                            },
                            "description": "List of source memories that were used (optional)",
                        },
                        "conversation_id": {
                            "type": "string",
                            "description": "Optional conversation ID (optional)",
                        },
                        "auto_save": {
                            "type": "boolean",
                            "description": "Override auto_save_responses setting (optional)",
                        },
                    },
                    "required": ["user_query", "ai_response"],
                },
            },
            {
                "name": "configure_autonomous_mode",
                "description": "Configure autonomous hooks behavior (enable/disable auto-search, auto-save, etc.)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "auto_search": {
                            "type": "boolean",
                            "description": "Enable/disable automatic vault search on every query",
                        },
                        "auto_save_queries": {
                            "type": "boolean",
                            "description": "Enable/disable saving every query (usually disabled to avoid noise)",
                        },
                        "auto_save_responses": {
                            "type": "boolean",
                            "description": "Enable/disable saving complete interactions (recommended: enabled)",
                        },
                        "min_query_length": {
                            "type": "number",
                            "description": "Minimum query length to process (default: 10)",
                        },
                    },
                },
            },
            {
                "name": "get_autonomous_config",
                "description": "Get current autonomous hooks configuration and recommendations",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "auto_hook_turn",
                "description": (
                    "💾 SAVE TURN (UNIFIED) — Call ONCE at the end of every substantive turn "
                    "to persist the exchange. Replaces the auto_hook_query + auto_hook_response "
                    "pair with a single call, halving the chance of forgetting.\n\n"
                    "The server's capture mode (low/mid/high) decides what actually saves:\n"
                    "  • low  — never saves\n"
                    "  • mid  — saves filtered turns (default)\n"
                    "  • high — saves every substantive turn\n\n"
                    "Pass mode='low'|'mid'|'high' to override per-call."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_query": {
                            "type": "string",
                            "description": "The user's verbatim message for this turn",
                        },
                        "ai_response": {
                            "type": "string",
                            "description": "The assistant's complete reply",
                        },
                        "sources_used": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "title": {"type": "string"},
                                },
                            },
                            "description": "Optional vault sources cited in the reply",
                        },
                        "conversation_id": {
                            "type": "string",
                            "description": "Optional stable conversation identifier",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["low", "mid", "high"],
                            "description": "Per-call override of capture mode (optional)",
                        },
                    },
                    "required": ["user_query", "ai_response"],
                },
            },
            {
                "name": "configure_capture_mode",
                "description": (
                    "Switch the capture mode at runtime. "
                    "low = search only (no saves); "
                    "mid = filtered save (default); "
                    "high = save every substantive turn."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["low", "mid", "high"],
                            "description": "Capture mode to activate",
                        },
                    },
                    "required": ["mode"],
                },
            },
            {
                "name": "get_capture_mode",
                "description": "Get the current capture mode and a description of each mode.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "relate_memories",
                "description": "Create a wikilink connection between two memories in the graph. This builds the knowledge graph by linking related ideas.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_id": {
                            "type": "string",
                            "description": "ID of the source memory",
                        },
                        "target_id": {
                            "type": "string",
                            "description": "ID of the target memory to link to",
                        },
                        "relationship": {
                            "type": "string",
                            "description": "Optional description of the relationship (e.g., 'related to', 'builds on', 'contradicts')",
                        },
                    },
                    "required": ["source_id", "target_id"],
                },
            },
            {
                "name": "search_by_graph",
                "description": "Traverse the knowledge graph from a memory to find connected memories within N hops. Reveals how ideas connect through wikilinks.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {
                            "type": "string",
                            "description": "Starting memory ID",
                        },
                        "depth": {
                            "type": "number",
                            "description": "How many hops to traverse (default: 2)",
                            "default": 2,
                        },
                        "include_backlinks": {
                            "type": "boolean",
                            "description": "Whether to follow backlinks (default: true)",
                            "default": True,
                        },
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "find_path",
                "description": "Find the shortest path between two memories through the knowledge graph. Shows how two ideas connect through intermediate memories.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "from_id": {
                            "type": "string",
                            "description": "Starting memory ID",
                        },
                        "to_id": {
                            "type": "string",
                            "description": "Target memory ID",
                        },
                    },
                    "required": ["from_id", "to_id"],
                },
            },
            {
                "name": "bulk_create",
                "description": "Create multiple memories in one operation. More efficient than calling create_memory multiple times.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memories": {
                            "type": "array",
                            "description": "List of memory objects to create",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "content": {"type": "string"},
                                    "memory_type": {
                                        "type": "string",
                                        "enum": [
                                            "episodic",
                                            "semantic",
                                            "procedural",
                                            "fact",
                                        ],
                                        "default": "semantic",
                                    },
                                    "tags": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "salience": {
                                        "type": "number",
                                        "default": 0.7,
                                    },
                                },
                                "required": ["title", "content"],
                            },
                        },
                    },
                    "required": ["memories"],
                },
            },
            {
                "name": "verify_last_save",
                "description": (
                    "🔍 VERIFY AUTO-SAVE - Check if your last conversation was saved.\n\n"
                    "Use this to:\n"
                    "- Confirm auto-save is working\n"
                    "- Debug save issues\n"
                    "- Get peace of mind that exchanges are being preserved\n\n"
                    "Returns details about the most recent save or troubleshooting tips if none found."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "time_window_seconds": {
                            "type": "number",
                            "description": "How far back to check in seconds (default: 60)",
                            "default": 60,
                        },
                        "conversation_only": {
                            "type": "boolean",
                            "description": "Only check conversation memories (default: true)",
                            "default": True,
                        },
                    },
                },
            },
            {
                "name": "get_save_stats",
                "description": (
                    "📊 SAVE STATISTICS - Get statistics about auto-save success rate.\n\n"
                    "Shows:\n"
                    "- How many saves have succeeded vs failed\n"
                    "- Save rate percentage\n"
                    "- Memory counts by type\n"
                    "- Status interpretation (excellent/good/poor/critical)\n\n"
                    "Helps you understand if auto-save is working effectively."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "enum": ["session", "hour", "day", "week", "all"],
                            "description": "Time period to analyze (default: session)",
                            "default": "session",
                        },
                    },
                },
            },
            {
                "name": "get_auto_save_analytics",
                "description": (
                    "📊 AUTO-SAVE ANALYTICS - Get comprehensive analytics on the hybrid auto-save system.\n\n"
                    "Shows detailed metrics:\n"
                    "- Overall save rate and performance grade (A+ to F)\n"
                    "- Layer 1 (explicit AI saves) vs Layer 2 (monitor) breakdown\n"
                    "- Total conversations saved vs estimated missed\n"
                    "- Monitor statistics (if enabled)\n"
                    "- Actionable recommendations for improvement\n\n"
                    "Use this to understand auto-save effectiveness and optimize configuration."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "enum": ["hour", "day", "week", "all"],
                            "description": "Time period for analytics (default: day)",
                            "default": "day",
                        },
                        "include_recommendations": {
                            "type": "boolean",
                            "description": "Include improvement recommendations (default: true)",
                            "default": True,
                        },
                    },
                },
            },
            {
                "name": "get_monitor_status",
                "description": (
                    "🔍 MONITOR DIAGNOSTICS - Check if Layer 2 conversation monitor is running.\n\n"
                    "Shows:\n"
                    "- Whether monitor is enabled and active\n"
                    "- Detection statistics\n"
                    "- Background loop status\n"
                    "- Recent activity\n\n"
                    "Use this to diagnose why auto-save isn't working."
                ),
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "suggest_tags",
                "description": "Suggest tags for a note using AI analysis. Analyzes content using frequency, semantic similarity, structure, and related notes to recommend relevant tags.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Note content to analyze",
                        },
                        "title": {
                            "type": "string",
                            "description": "Note title (optional)",
                        },
                        "existing_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags already assigned to the note (optional)",
                        },
                        "min_confidence": {
                            "type": "number",
                            "description": "Minimum confidence score 0.0-1.0 (default: 0.3)",
                            "default": 0.3,
                        },
                        "max_suggestions": {
                            "type": "integer",
                            "description": "Maximum number of suggestions (default: 5)",
                            "default": 5,
                        },
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "suggest_links",
                "description": "Suggest wikilinks for a note using semantic similarity and graph analysis. Analyzes content, graph relationships, and context to recommend relevant connections to other notes. Includes bidirectional link suggestions (notes that should link to this one).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Note content to analyze",
                        },
                        "title": {
                            "type": "string",
                            "description": "Note title (optional)",
                        },
                        "note_id": {
                            "type": "string",
                            "description": "Note ID for graph-based suggestions (optional)",
                        },
                        "existing_links": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Links already in the note to exclude (optional)",
                        },
                        "min_confidence": {
                            "type": "number",
                            "description": "Minimum confidence score 0.0-1.0 (default: 0.4)",
                            "default": 0.4,
                        },
                        "max_suggestions": {
                            "type": "integer",
                            "description": "Maximum number of suggestions (default: 10)",
                            "default": 10,
                        },
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "detect_knowledge_gaps",
                "description": "Detect knowledge gaps in the vault including missing topics, weak coverage, isolated notes, and missing links. Provides actionable suggestions for improving the knowledge base structure and completeness.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "min_severity": {
                            "type": "number",
                            "description": "Minimum severity threshold 0.0-1.0 (default: 0.3)",
                            "default": 0.3,
                        },
                        "max_gaps": {
                            "type": "integer",
                            "description": "Maximum number of gaps to return (default: 20)",
                            "default": 20,
                        },
                        "gap_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "missing_topic",
                                    "weak_coverage",
                                    "isolated_note",
                                    "missing_link",
                                ],
                            },
                            "description": "Specific gap types to detect (optional). Options: missing_topic, weak_coverage, isolated_note, missing_link",
                        },
                    },
                },
            },
            {
                "name": "analyze_knowledge_base",
                "description": "Perform comprehensive knowledge base analysis including gap detection, topic clustering, and learning path suggestions. Provides insights into the structure, completeness, and organization of the knowledge base with actionable recommendations.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_gaps": {
                            "type": "boolean",
                            "description": "Include gap detection analysis (default: true)",
                            "default": True,
                        },
                        "include_clusters": {
                            "type": "boolean",
                            "description": "Include topic clustering analysis (default: true)",
                            "default": True,
                        },
                        "include_paths": {
                            "type": "boolean",
                            "description": "Include learning path suggestions (default: true)",
                            "default": True,
                        },
                    },
                },
            },
        ]
