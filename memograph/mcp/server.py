"""MCP Server implementation for MemoGraph.

This module provides an MCP (Model Context Protocol) server that exposes
MemoGraph functionality as tools that can be used by any MCP-compatible
AI client (Claude Desktop, Cline, etc.).
"""

import logging
import os
from pathlib import Path
from typing import Any

from ..core.enums import MemoryType
from ..core.kernel import MemoryKernel
from .autonomous_hooks import AutonomousHooks

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
            raise PermissionError(
                f"No write permission for vault: {self.vault_path}"
            )
        
        logger.info(f"✓ Vault validated: {self.vault_path}")
        
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
            if stats['indexed'] == 0 and stats['skipped'] == 0:
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
    
    def _atomic_write(self, file_path: Path, content: str) -> None:
        """Write file atomically using temp file + rename to prevent corruption.
        
        Args:
            file_path: Target file path to write to
            content: Content to write
            
        Raises:
            OSError: If write or rename fails
        """
        temp_path = file_path.with_suffix('.tmp')
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

            return self._add_vault_context(
                {
                    "success": True,
                    "count": len(formatted_results),
                    "results": formatted_results,
                }
            )

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
                candidates = self.kernel.graph.get_by_tags(list(new_tags), match_all=False)
            else:
                # If no tags, just check recent memories
                all_nodes = self.kernel.graph.all_nodes()
                from datetime import datetime
                candidates = sorted(
                    all_nodes,
                    key=lambda n: n.created_at or datetime.min,
                    reverse=True
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

            return self._add_vault_context(
                {
                    "success": True,
                    "message": f"Created memory: {title}",
                    "path": path,
                    "title": title,
                    "suggested_links": suggested_links,
                }
            )

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

                return self._add_vault_context(
                    {
                        "success": True,
                        "answer": answer,
                        "sources": formatted_sources,
                        "question": question,
                        "mode": "generated",
                    }
                )

            # Otherwise, return context for client's LLM to use
            else:
                return self._add_vault_context(
                    {
                        "success": True,
                        "context": context,
                        "sources": formatted_sources,
                        "question": question,
                        "mode": "context_only",
                        "message": "Use the provided context to answer the question. The context includes relevant memories from the vault with source citations [S1], [S2], etc.",
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

    async def get_vault_stats(self) -> dict[str, Any]:
        """Get statistics about the vault.

        Returns:
            Dictionary with vault statistics
        """
        try:
            self._check_server_health()
            # Ingest to get stats
            stats = self.kernel.ingest(force=False)

            # Get additional info
            all_nodes = self.kernel.graph.all_nodes()

            # Count by type
            type_counts: dict[str, int] = {}
            for node in all_nodes:
                type_name = node.memory_type.value
                type_counts[type_name] = type_counts.get(type_name, 0) + 1

            # Get all tags
            all_tags = set()
            for node in all_nodes:
                all_tags.update(node.tags)

            return self._add_vault_context(
                {
                    "success": True,
                    "vault_path": str(self.vault_path),
                    "total_memories": stats["total"],
                    "indexed": stats["indexed"],
                    "skipped": stats["skipped"],
                    "by_type": type_counts,
                    "total_tags": len(all_tags),
                    "tags": sorted(all_tags),
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
                        "auto_hook_query",
                        "auto_hook_response",
                        "configure_autonomous_mode",
                        "get_autonomous_config",
                    ],
                    "graph": [
                        "relate_memories",
                        "search_by_graph",
                        "find_path",
                    ],
                    "bulk": ["bulk_create"],
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
                
                logger.debug(f"Updated graph incrementally for link: {source_id} -> {target_id}")

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
                "name": "list_available_tools",
                "description": "List all available MCP tools with their descriptions and categories",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "auto_hook_query",
                "description": "Autonomous hook for user queries - automatically searches vault and provides context. Call this at the START of every user interaction to get relevant context automatically.",
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
                "description": "Autonomous hook for AI responses - saves the complete interaction. Call this at the END of every user interaction to save the conversation automatically.",
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
        ]
