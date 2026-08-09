"""Tests for Notion API client wrapper."""

import pytest
from unittest.mock import patch, MagicMock

# Skip all tests in this module if notion-client is not installed
pytest.importorskip("notion_client", reason="notion-client package not installed")

from memograph.integrations.notion.client import NotionClient  # noqa: E402


class TestNotionClient:
    """Test NotionClient initialization and basic operations."""

    def test_init_with_token(self):
        """Test initialization with explicit token."""
        with patch("notion_client.Client"):
            client = NotionClient(auth_token="secret_test_token")
            assert client.auth_token == "secret_test_token"

    def test_init_from_env(self, monkeypatch):
        """Test initialization from environment variable."""
        monkeypatch.setenv("NOTION_API_TOKEN", "secret_env_token")
        with patch("notion_client.Client"):
            client = NotionClient()
            assert client.auth_token == "secret_env_token"

    def test_init_no_token_raises_error(self, monkeypatch):
        """Test that missing token raises ValueError."""
        monkeypatch.delenv("NOTION_API_TOKEN", raising=False)
        with patch("notion_client.Client"):
            with pytest.raises(ValueError, match="Notion API token required"):
                NotionClient()

    def test_init_missing_package_raises_error(self):
        """Test that a missing notion-client package raises a clear ImportError.

        Simulate the package being absent by making ``from notion_client
        import Client`` fail: block the import so the ``except ImportError``
        branch in ``NotionClient.__init__`` runs.
        """
        import builtins

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "notion_client" or name.startswith("notion_client."):
                raise ImportError("No module named 'notion_client'")
            return real_import(name, *args, **kwargs)

        with patch.dict("sys.modules", {"notion_client": None}):
            with patch("builtins.__import__", side_effect=_blocked_import):
                with pytest.raises(
                    ImportError, match="notion-client package not installed"
                ):
                    NotionClient(auth_token="test")

    def test_test_connection_success(self):
        """Test successful connection test."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.users.me.return_value = {"id": "user_123"}
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            assert client.test_connection() is True
            mock_client.users.me.assert_called_once()

    def test_test_connection_failure(self):
        """Test connection test failure."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.users.me.side_effect = Exception("Connection failed")
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            assert client.test_connection() is False

    def test_get_user_info(self):
        """Test getting user information."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.users.me.return_value = {"id": "user_123", "name": "Test User"}
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            user_info = client.get_user_info()
            assert user_info["id"] == "user_123"
            assert user_info["name"] == "Test User"

    def test_search_pages(self):
        """Test searching for pages."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.search.return_value = {
                "results": [
                    {"id": "page_1", "object": "page"},
                    {"id": "page_2", "object": "page"},
                ]
            }
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            pages = client.search_pages(query="test")

            assert len(pages) == 2
            assert pages[0]["id"] == "page_1"
            mock_client.search.assert_called_once()

    def test_list_pages_without_database(self):
        """Test listing all pages."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.search.return_value = {"results": [{"id": "page_1"}]}
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            pages = client.list_pages()

            assert len(pages) == 1
            mock_client.search.assert_called_once()

    def test_list_pages_with_database(self):
        """Test listing pages from a specific database."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.databases.query.return_value = {"results": [{"id": "page_1"}]}
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            pages = client.list_pages(database_id="db_123")

            assert len(pages) == 1
            mock_client.databases.query.assert_called_once_with(database_id="db_123")

    def test_get_page(self):
        """Test retrieving a single page."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.pages.retrieve.return_value = {
                "id": "page_123",
                "properties": {},
            }
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            page = client.get_page("page_123")

            assert page["id"] == "page_123"
            mock_client.pages.retrieve.assert_called_once_with(page_id="page_123")

    def test_get_blocks(self):
        """Test getting child blocks."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.blocks.children.list.return_value = {
                "results": [
                    {"id": "block_1", "type": "paragraph"},
                    {"id": "block_2", "type": "heading_1"},
                ]
            }
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            blocks = client.get_blocks("page_123")

            assert len(blocks) == 2
            assert blocks[0]["type"] == "paragraph"
            mock_client.blocks.children.list.assert_called_once()

    def test_get_all_blocks_with_pagination(self):
        """Test getting all blocks with pagination handling."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            # Simulate pagination
            mock_client.blocks.children.list.side_effect = [
                {
                    "results": [{"id": "block_1"}],
                    "has_more": True,
                    "next_cursor": "cursor_1",
                },
                {
                    "results": [{"id": "block_2"}],
                    "has_more": False,
                    "next_cursor": None,
                },
            ]
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            blocks = client.get_all_blocks("page_123")

            assert len(blocks) == 2
            assert mock_client.blocks.children.list.call_count == 2

    def test_create_page(self):
        """Test creating a new page."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.pages.create.return_value = {
                "id": "new_page_123",
                "object": "page",
            }
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            parent = {"database_id": "db_123"}
            properties = {"title": {"title": [{"text": {"content": "New Page"}}]}}

            page = client.create_page(parent, properties)

            assert page["id"] == "new_page_123"
            mock_client.pages.create.assert_called_once()

    def test_update_page(self):
        """Test updating a page."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.pages.update.return_value = {"id": "page_123", "object": "page"}
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            properties = {"title": {"title": [{"text": {"content": "Updated"}}]}}

            page = client.update_page("page_123", properties=properties)

            assert page["id"] == "page_123"
            mock_client.pages.update.assert_called_once()

    def test_get_database(self):
        """Test retrieving a database."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.databases.retrieve.return_value = {
                "id": "db_123",
                "title": [{"text": {"content": "My Database"}}],
            }
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            database = client.get_database("db_123")

            assert database["id"] == "db_123"
            mock_client.databases.retrieve.assert_called_once_with(database_id="db_123")

    def test_query_database(self):
        """Test querying a database with filters."""
        with patch("notion_client.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.databases.query.return_value = {
                "results": [{"id": "page_1"}, {"id": "page_2"}]
            }
            mock_client_class.return_value = mock_client

            client = NotionClient(auth_token="secret_test")
            filter_params = {"property": "Status", "select": {"equals": "Done"}}

            pages = client.query_database("db_123", filter_params=filter_params)

            assert len(pages) == 2
            mock_client.databases.query.assert_called_once()
