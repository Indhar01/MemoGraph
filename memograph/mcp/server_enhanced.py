"""Enhanced MCP Server implementation for MemoGraph.

This file contains additional enhanced tools that can be integrated into the main server.py file.
These tools provide advanced CRUD, analytics, and maintenance capabilities.
"""

import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

import yaml

from ..core.enums import MemoryType

logger = logging.getLogger(__name__)


class EnhancedMCPTools:
    """Enhanced tools for MemoGraph MCP Server."""

    def __init__(self, server):
        """Initialize with reference to main server instance."""
        self.server = server
        self.vault_path = server.vault_path
        self.kernel = server.kernel

    async def list_available_tools(self) -> dict[str, Any]:
        """List all available MCP tools with descriptions.

        Returns:
            Dictionary with list of available tools and their descriptions
        """
        try:
            tools_info = []
            for tool in self.server.get_tools_schema():
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
                    "search": ["search_vault", "query_with_context", "find_similar_memories"],
                    "create": ["create_memory", "batch_create_memories", "import_document"],
                    "read": ["get_memory", "list_memories", "get_memory_connections"],
                    "update": ["update_memory"],
                    "delete": ["delete_memory", "bulk_delete_memories"],
                    "analytics": ["get_vault_stats", "get_vault_analytics", "get_tag_statistics"],
                    "maintenance": [
                        "reindex_vault",
                        "validate_vault",
                        "export_memories",
                        "backup_vault",
                    ],
                },
            }
        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def delete_memory(self, memory_id: str) -> dict[str, Any]:
        """Delete a memory from the vault.

        Args:
            memory_id: ID of the memory to delete

        Returns:
            Dictionary with deletion result
        """
        try:
            # Find the memory file
            memory_path = None
            for md_file in self.vault_path.rglob("*.md"):
                if md_file.stem == memory_id or md_file.stem.startswith(f"{memory_id}-"):
                    memory_path = md_file
                    break

            if not memory_path or not memory_path.exists():
                # Fuzzy match suggestion
                all_ids = [f.stem for f in self.vault_path.rglob("*.md")]
                suggestions = self._fuzzy_match(memory_id, all_ids, n=3)
                error_msg = f"Memory not found: {memory_id}"
                if suggestions:
                    error_msg += f". Did you mean: {', '.join(suggestions)}?"

                return {
                    "success": False,
                    "error": error_msg,
                }

            # Get memory info before deletion
            node = self.kernel.graph.get(memory_id)
            title = node.title if node else memory_id

            # Delete the file
            memory_path.unlink()

            # Remove from graph
            if node:
                self.kernel.graph._nodes.pop(memory_id, None)

            logger.info(f"Deleted memory: {memory_id}")

            return {
                "success": True,
                "message": f"Deleted memory: {title}",
                "memory_id": memory_id,
            }

        except Exception as e:
            logger.error(f"Error deleting memory: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def update_memory(
        self,
        memory_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[list[str]] = None,
        salience: Optional[float] = None,
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
            import re

            # Find the memory file
            memory_path = None
            for md_file in self.vault_path.rglob("*.md"):
                if md_file.stem == memory_id or md_file.stem.startswith(f"{memory_id}-"):
                    memory_path = md_file
                    break

            if not memory_path or not memory_path.exists():
                all_ids = [f.stem for f in self.vault_path.rglob("*.md")]
                suggestions = self._fuzzy_match(memory_id, all_ids, n=3)
                error_msg = f"Memory not found: {memory_id}"
                if suggestions:
                    error_msg += f". Did you mean: {', '.join(suggestions)}?"

                return {
                    "success": False,
                    "error": error_msg,
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
                    return {"success": False, "error": "Salience must be between 0.0 and 1.0"}
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
                "---\n" + yaml.safe_dump(frontmatter, sort_keys=False).strip() + "\n---\n\n"
            )
            memory_path.write_text(new_frontmatter + body + "\n", encoding="utf-8")

            logger.info(f"Updated memory: {memory_id}")

            return {
                "success": True,
                "message": f"Updated memory: {frontmatter['title']}",
                "memory_id": memory_id,
            }

        except Exception as e:
            logger.error(f"Error updating memory: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def batch_create_memories(
        self,
        memories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create multiple memories at once.

        Args:
            memories: List of memory dictionaries with title, content, etc.

        Returns:
            Dictionary with batch creation results
        """
        try:
            paths, errors = self.kernel.remember_many(memories, continue_on_error=True)

            return {
                "success": len(errors) == 0,
                "created": len(paths),
                "failed": len(errors),
                "paths": paths,
                "errors": [
                    {"memory": err[0].get("title", "unknown"), "error": str(err[1])}
                    for err in errors
                ],
            }

        except Exception as e:
            logger.error(f"Error batch creating memories: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def bulk_delete_memories(
        self,
        memory_ids: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        memory_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Delete multiple memories by filter.

        Args:
            memory_ids: Specific memory IDs to delete
            tags: Delete memories with these tags
            memory_type: Delete memories of this type

        Returns:
            Dictionary with bulk deletion results
        """
        try:
            deleted = []
            errors = []

            # Get all nodes
            nodes = self.kernel.graph.all_nodes()

            # Apply filters
            if memory_ids:
                nodes = [n for n in nodes if n.id in memory_ids]
            if tags:
                nodes = [n for n in nodes if any(tag in n.tags for tag in tags)]
            if memory_type:
                try:
                    mem_type = MemoryType(memory_type)
                    nodes = [n for n in nodes if n.memory_type == mem_type]
                except ValueError:
                    pass

            if len(nodes) == 0:
                return {
                    "success": True,
                    "message": "No memories matched the filter criteria",
                    "deleted": 0,
                    "failed": 0,
                }

            # Delete each memory
            for node in nodes:
                try:
                    result = await self.delete_memory(node.id)
                    if result["success"]:
                        deleted.append(node.id)
                    else:
                        errors.append(
                            {"memory_id": node.id, "error": result.get("error", "Unknown error")}
                        )
                except Exception as e:
                    errors.append({"memory_id": node.id, "error": str(e)})

            return {
                "success": len(errors) == 0,
                "deleted": len(deleted),
                "failed": len(errors),
                "memory_ids": deleted,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Error bulk deleting memories: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def get_vault_analytics(self) -> dict[str, Any]:
        """Get advanced analytics about the vault.

        Returns:
            Dictionary with detailed analytics
        """
        try:
            nodes = self.kernel.graph.all_nodes()

            # Basic stats
            total = len(nodes)
            if total == 0:
                return {
                    "success": True,
                    "message": "Vault is empty",
                    "total_memories": 0,
                }

            # Calculate statistics
            salience_scores = [n.salience for n in nodes]
            avg_salience = sum(salience_scores) / len(salience_scores)

            # Type distribution
            type_counts: dict[str, int] = {}
            for node in nodes:
                type_name = node.memory_type.value
                type_counts[type_name] = type_counts.get(type_name, 0) + 1

            # Tag statistics
            tag_counts: dict[str, int] = {}
            for node in nodes:
                for tag in node.tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

            # Most connected memories (by links + backlinks)
            most_connected = sorted(
                [(n.id, n.title, len(n.links) + len(n.backlinks)) for n in nodes],
                key=lambda x: x[2],
                reverse=True,
            )[:10]

            # Most important memories (by salience)
            most_important = sorted(
                [(n.id, n.title, n.salience) for n in nodes], key=lambda x: x[2], reverse=True
            )[:10]

            # Recent activity
            recent = sorted(
                [
                    (n.id, n.title, n.created_at.isoformat() if n.created_at else "")
                    for n in nodes
                    if n.created_at
                ],
                key=lambda x: x[2],
                reverse=True,
            )[:10]

            return {
                "success": True,
                "total_memories": total,
                "average_salience": round(avg_salience, 3),
                "type_distribution": type_counts,
                "top_tags": sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:20],
                "most_connected": [
                    {"id": m[0], "title": m[1], "connections": m[2]} for m in most_connected
                ],
                "most_important": [
                    {"id": m[0], "title": m[1], "salience": m[2]} for m in most_important
                ],
                "recent_memories": [
                    {"id": m[0], "title": m[1], "created_at": m[2]} for m in recent
                ],
            }

        except Exception as e:
            logger.error(f"Error getting vault analytics: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def get_memory_connections(self, memory_id: str) -> dict[str, Any]:
        """Get connections for a specific memory.

        Args:
            memory_id: Memory ID

        Returns:
            Dictionary with connection information
        """
        try:
            node = self.kernel.graph.get(memory_id)
            if not node:
                return {
                    "success": False,
                    "error": f"Memory not found: {memory_id}",
                }

            # Get direct connections
            outgoing = []
            for link_id in node.links:
                link_node = self.kernel.graph.get(link_id)
                if link_node:
                    outgoing.append(
                        {
                            "id": link_node.id,
                            "title": link_node.title,
                            "memory_type": link_node.memory_type.value,
                            "tags": link_node.tags,
                        }
                    )

            incoming = []
            for link_id in node.backlinks:
                link_node = self.kernel.graph.get(link_id)
                if link_node:
                    incoming.append(
                        {
                            "id": link_node.id,
                            "title": link_node.title,
                            "memory_type": link_node.memory_type.value,
                            "tags": link_node.tags,
                        }
                    )

            return {
                "success": True,
                "memory_id": memory_id,
                "title": node.title,
                "outgoing_connections": len(outgoing),
                "incoming_connections": len(incoming),
                "outgoing": outgoing,
                "incoming": incoming,
            }

        except Exception as e:
            logger.error(f"Error getting memory connections: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def _fuzzy_match(self, target: str, candidates: list[str], n: int = 3) -> list[str]:
        """Find fuzzy matches for a target string.

        Args:
            target: String to match
            candidates: List of candidate strings
            n: Number of matches to return

        Returns:
            List of best matching candidates
        """
        scores = [(c, SequenceMatcher(None, target.lower(), c.lower()).ratio()) for c in candidates]
        scores.sort(key=lambda x: x[1], reverse=True)
        return [c for c, score in scores[:n] if score > 0.5]
