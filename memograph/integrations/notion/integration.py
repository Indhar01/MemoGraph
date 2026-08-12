"""Notion integration implementation for MemoGraph."""

from typing import Dict, List, Any, Optional
from datetime import datetime
import asyncio

from memograph.integrations.base import IntegrationBase
from memograph.integrations.notion.client import NotionClient


class NotionIntegration(IntegrationBase):
    """Notion integration for MemoGraph.

    .. warning::
        **Experimental / incomplete.** Connection, authentication, and
        page *listing* work, but two-way synchronization is not yet
        implemented: ``_sync_pull`` currently only counts pages and
        ``_sync_push`` is a no-op. Do not rely on this for production
        data movement. Tracked for a future release.

    Intended to provide bidirectional synchronization between MemoGraph
    and Notion (pages, blocks, properties, databases) once the sync
    engine lands.

    Attributes:
        client: NotionClient instance for API access
        workspace_id: Optional workspace ID for filtering

    Example:
        ```python
        integration = NotionIntegration(auth_token="secret_...")

        # Pull changes from Notion
        result = await integration.sync(direction="pull")

        # Push changes to Notion
        result = await integration.sync(direction="push")

        # Bidirectional sync
        result = await integration.sync(direction="bidirectional")
        ```
    """

    def __init__(
        self, auth_token: Optional[str] = None, workspace_id: Optional[str] = None
    ):
        """Initialize Notion integration.

        Args:
            auth_token: Notion API token (or use NOTION_API_TOKEN env var)
            workspace_id: Optional workspace ID for filtering pages
        """
        self.client = NotionClient(auth_token)
        self.workspace_id = workspace_id
        self._verify_connection()

    def _verify_connection(self) -> None:
        """Verify connection to Notion API on initialization.

        Raises:
            ConnectionError: If connection to Notion API fails.
        """
        if not self.client.test_connection():
            raise ConnectionError(
                "Failed to connect to Notion API. Please check your "
                "authentication token and internet connection."
            )

    async def sync(self, direction: str = "bidirectional") -> Dict[str, Any]:
        """Sync data between MemoGraph and Notion.

        Args:
            direction: Sync direction - "pull", "push", or "bidirectional"

        Returns:
            Dictionary with sync results:
            {
                "direction": str,
                "pages_pulled": int,
                "pages_pushed": int,
                "errors": List[str],
                "timestamp": str
            }

        Raises:
            ValueError: If invalid direction provided
        """
        if direction not in ["pull", "push", "bidirectional"]:
            raise ValueError(
                f"Invalid sync direction: {direction}. "
                "Must be 'pull', 'push', or 'bidirectional'"
            )

        result: Dict[str, Any] = {
            "direction": direction,
            "pages_pulled": 0,
            "pages_pushed": 0,
            "errors": [],
            "timestamp": datetime.now().isoformat(),
        }

        try:
            if direction in ["pull", "bidirectional"]:
                pulled = await self._sync_pull()
                result["pages_pulled"] = pulled

            if direction in ["push", "bidirectional"]:
                pushed = await self._sync_push()
                result["pages_pushed"] = pushed

        except Exception as e:
            result["errors"].append(f"Sync failed: {str(e)}")

        return result

    async def _sync_pull(self) -> int:
        """Pull changes from Notion to MemoGraph.

        Returns:
            Number of pages pulled.
        """
        # TODO: Implement pull logic in future tasks
        # This will be implemented in Task P1-W10-T1 (Bidirectional Sync Engine)
        pages = await asyncio.to_thread(self.client.list_pages)
        return len(pages)

    async def _sync_push(self) -> int:
        """Push changes from MemoGraph to Notion.

        Returns:
            Number of pages pushed.
        """
        # TODO: Implement push logic in future tasks
        # This will be implemented in Task P1-W10-T1 (Bidirectional Sync Engine)
        return 0

    async def get_modified_items(self, since: datetime) -> List[Dict[str, Any]]:
        """Get items modified since a specific timestamp.

        Args:
            since: Datetime to filter by (last_edited_time)

        Returns:
            List of modified page objects.
        """
        # Get all pages (Notion API doesn't support timestamp filtering in search)
        pages = await asyncio.to_thread(self.client.search_pages)

        # Filter by last_edited_time
        modified_pages = []
        for page in pages:
            last_edited = page.get("last_edited_time", "")
            if last_edited:
                page_time = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
                if page_time >= since:
                    modified_pages.append(page)

        return modified_pages

    async def push_item(self, item: Dict[str, Any]) -> bool:
        """Push an item from MemoGraph to Notion.

        Args:
            item: Item data to push (must include 'parent' and 'properties')

        Returns:
            True if successful, False otherwise.
        """
        try:
            parent = item.get("parent")
            properties = item.get("properties")
            children = item.get("children")

            if not parent or not properties:
                raise ValueError("Item must include 'parent' and 'properties'")

            # Create page in Notion
            page = await asyncio.to_thread(
                self.client.create_page,
                parent=parent,
                properties=properties,
                children=children,
            )

            return bool(page.get("id"))

        except Exception as e:
            print(f"Failed to push item: {e}")
            return False

    async def pull_item(self, item_id: str) -> Dict[str, Any]:
        """Pull an item from Notion to MemoGraph.

        Args:
            item_id: Notion page ID

        Returns:
            Dictionary containing page data and blocks:
            {
                "page": Dict[str, Any],
                "blocks": List[Dict[str, Any]],
                "timestamp": str
            }
        """
        page = await asyncio.to_thread(self.client.get_page, item_id)
        blocks = await asyncio.to_thread(self.client.get_all_blocks, item_id)

        return {"page": page, "blocks": blocks, "timestamp": datetime.now().isoformat()}

    async def get_page_hierarchy(self, page_id: str) -> Dict[str, Any]:
        """Get the full hierarchy of a page (parents and children).

        Args:
            page_id: Notion page ID

        Returns:
            Dictionary with page and its relationships:
            {
                "page": Dict[str, Any],
                "parent": Optional[Dict[str, Any]],
                "children": List[Dict[str, Any]]
            }
        """
        page = await asyncio.to_thread(self.client.get_page, page_id)

        # Get parent information
        parent = page.get("parent")
        parent_data = None
        if parent:
            parent_type = parent.get("type")
            parent_id = parent.get(parent_type)
            if parent_id and parent_type == "page_id":
                try:
                    parent_data = await asyncio.to_thread(
                        self.client.get_page, parent_id
                    )
                except Exception:
                    parent_data = None

        # Get child pages
        blocks = await asyncio.to_thread(self.client.get_all_blocks, page_id)
        child_pages = []
        for block in blocks:
            if block.get("type") == "child_page":
                child_id = block.get("id")
                try:
                    child_page = await asyncio.to_thread(self.client.get_page, child_id)
                    child_pages.append(child_page)
                except Exception:
                    continue

        return {"page": page, "parent": parent_data, "children": child_pages}

    async def search(
        self, query: str, filter_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for pages in Notion workspace.

        Args:
            query: Search query text
            filter_type: Optional filter ("page" or "database")

        Returns:
            List of matching page objects.
        """
        return await asyncio.to_thread(
            self.client.search_pages, query=query, filter_type=filter_type
        )

    async def get_database_pages(
        self, database_id: str, filter_params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Get all pages from a Notion database.

        Args:
            database_id: Notion database ID
            filter_params: Optional filter conditions

        Returns:
            List of page objects from the database.
        """
        return await asyncio.to_thread(
            self.client.query_database,
            database_id=database_id,
            filter_params=filter_params,
        )

    def get_connection_info(self) -> Dict[str, Any]:
        """Get information about the current Notion connection.

        Returns:
            Dictionary with connection information:
            {
                "connected": bool,
                "user": Dict[str, Any],
                "workspace_id": Optional[str]
            }
        """
        try:
            user = self.client.get_user_info()
            return {"connected": True, "user": user, "workspace_id": self.workspace_id}
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
                "workspace_id": self.workspace_id,
            }
