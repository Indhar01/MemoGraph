"""Tests for :class:`memograph.sources.notion.NotionSource`.

The Notion client is mocked at the wrapper level
(:class:`memograph.integrations.notion.client.NotionClient`) so the
tests exercise the adapter's logic — list/read/materialize/health,
block-to-markdown rendering, error classification — without an
actual Notion workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from memograph.sources.base import (
    SourceAuthError,
    SourceConfig,
    SourceError,
    SourceHealthStatus,
    SourceKind,
    SourceReadOnlyError,
)
from memograph.sources.notion import (
    NotionSource,
    _blocks_to_markdown,
    _extract_title,
    _ref_from_page,
    _safe_filename,
)


def _config(**extras: Any) -> SourceConfig:
    params: dict[str, Any] = {"auth_token": "secret_test"}
    params.update(extras)
    return SourceConfig(
        source_id="notion-test",
        kind=SourceKind.NOTION,
        display_name="Notion Test",
        params=params,
    )


def _page(
    page_id: str = "abc123def456",
    title: str = "My Page",
    last_edited: str = "2026-06-20T12:00:00.000Z",
) -> dict[str, Any]:
    """Build a fake Notion page payload matching the API shape."""
    return {
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "last_edited_time": last_edited,
        "archived": False,
        "properties": {
            "title": {
                "type": "title",
                "title": [{"plain_text": title}],
            }
        },
    }


@pytest.fixture
def fake_client():
    """A MagicMock standing in for NotionClient. Tests configure its
    return values per case."""
    client = MagicMock()
    client.test_connection.return_value = True
    return client


@pytest.fixture
def patch_notion(fake_client, monkeypatch):
    """Replace NotionClient with a constructor that returns
    ``fake_client``."""
    from memograph.integrations.notion import client as client_mod

    def _factory(auth_token=None):
        return fake_client

    monkeypatch.setattr(client_mod, "NotionClient", _factory)
    return fake_client


class TestRefFromPage:
    def test_strips_dashes(self) -> None:
        page = _page(page_id="abc-123-def-456")
        ref = _ref_from_page(page)
        assert ref is not None
        assert ref.doc_id == "abc123def456"
        assert ref.title == "My Page"

    def test_returns_none_without_id(self) -> None:
        assert _ref_from_page({}) is None

    def test_falls_back_to_id_when_title_empty(self) -> None:
        page = {
            "id": "abc",
            "properties": {},
            "last_edited_time": "2026-01-01T00:00:00Z",
        }
        ref = _ref_from_page(page)
        assert ref is not None
        assert ref.title  # non-empty


class TestExtractTitle:
    def test_database_row_title(self) -> None:
        page = _page(title="From DB")
        assert _extract_title(page) == "From DB"

    def test_concatenates_rich_text_parts(self) -> None:
        page = {
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [
                        {"plain_text": "Part one "},
                        {"plain_text": "and two"},
                    ],
                }
            }
        }
        assert _extract_title(page) == "Part one and two"

    def test_no_title_returns_none(self) -> None:
        page = {"properties": {"Status": {"type": "select", "select": None}}}
        assert _extract_title(page) is None


class TestBlocksToMarkdown:
    def _block(self, btype: str, text: str = "", **extra: Any) -> dict[str, Any]:
        return {
            "type": btype,
            btype: {
                "rich_text": [{"plain_text": text}] if text else [],
                **extra,
            },
        }

    def test_paragraph(self) -> None:
        out = _blocks_to_markdown([self._block("paragraph", "Hello world")])
        assert out == "Hello world"

    def test_headings(self) -> None:
        out = _blocks_to_markdown(
            [
                self._block("heading_1", "H1"),
                self._block("heading_2", "H2"),
                self._block("heading_3", "H3"),
            ]
        )
        assert "# H1" in out
        assert "## H2" in out
        assert "### H3" in out

    def test_bulleted_and_numbered(self) -> None:
        out = _blocks_to_markdown(
            [
                self._block("bulleted_list_item", "alpha"),
                self._block("numbered_list_item", "beta"),
            ]
        )
        assert "- alpha" in out
        assert "1. beta" in out

    def test_to_do_checked_and_unchecked(self) -> None:
        out = _blocks_to_markdown(
            [
                self._block("to_do", "done", checked=True),
                self._block("to_do", "todo", checked=False),
            ]
        )
        assert "- [x] done" in out
        assert "- [ ] todo" in out

    def test_quote_code_divider(self) -> None:
        out = _blocks_to_markdown(
            [
                self._block("quote", "said it"),
                self._block("code", "print('hi')", language="python"),
                self._block("divider"),
            ]
        )
        assert "> said it" in out
        assert "```python" in out
        assert "---" in out

    def test_unknown_block_emits_comment(self) -> None:
        out = _blocks_to_markdown([{"type": "table", "table": {}}])
        assert "<!-- notion: table" in out


class TestSafeFilename:
    def test_strips_illegal_chars(self) -> None:
        assert "_" in _safe_filename("a:b/c?d")

    def test_truncates_long_titles(self) -> None:
        long = "x" * 500
        assert len(_safe_filename(long)) <= 120


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_lists_search_results(
        self, patch_notion
    ) -> None:
        fake = patch_notion
        fake.search_pages.return_value = [_page("aaa", "Alpha")]
        source = NotionSource(_config())
        refs = [r async for r in source.list_documents()]
        assert len(refs) == 1
        assert refs[0].doc_id == "aaa"
        assert refs[0].title == "Alpha"

    @pytest.mark.asyncio
    async def test_uses_database_query_when_database_id_set(
        self, patch_notion
    ) -> None:
        fake = patch_notion
        fake.list_pages.return_value = [_page("bbb", "Beta")]
        source = NotionSource(_config(database_id="db-1"))
        refs = [r async for r in source.list_documents()]
        fake.list_pages.assert_called_once_with(database_id="db-1")
        assert refs[0].title == "Beta"

    @pytest.mark.asyncio
    async def test_auth_error_classified(self, patch_notion) -> None:
        fake = patch_notion
        err = type("APIResponseError", (Exception,), {})("unauthorized")
        err.status = 401  # type: ignore[attr-defined]
        fake.search_pages.side_effect = err
        source = NotionSource(_config())
        with pytest.raises(SourceAuthError):
            [r async for r in source.list_documents()]


class TestReadDocument:
    @pytest.mark.asyncio
    async def test_round_trip(self, patch_notion) -> None:
        fake = patch_notion
        fake.get_page.return_value = _page("abc", "My Doc")
        fake.get_all_blocks.return_value = [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": "Hello"}]},
            },
        ]
        source = NotionSource(_config())
        doc = await source.read_document("abc")
        assert doc.ref.doc_id == "abc"
        assert "Hello" in doc.content

    @pytest.mark.asyncio
    async def test_not_found(self, patch_notion) -> None:
        fake = patch_notion
        err = type("APIResponseError", (Exception,), {})("missing")
        err.status = 404  # type: ignore[attr-defined]
        fake.get_page.side_effect = err
        source = NotionSource(_config())
        from memograph.sources.base import SourceNotFoundError

        with pytest.raises(SourceNotFoundError):
            await source.read_document("never-existed")


class TestWriteIsReadOnly:
    @pytest.mark.asyncio
    async def test_write_raises_read_only(self, patch_notion) -> None:
        from memograph.sources.base import (
            Document,
            DocumentRef,
        )
        from datetime import datetime as dt
        from datetime import timezone as tz

        source = NotionSource(_config())
        ref = DocumentRef(
            doc_id="x",
            title="x",
            modified_at=dt.now(tz.utc),
        )
        with pytest.raises(SourceReadOnlyError):
            await source.write_document(Document(ref=ref, content="hi"))

    def test_supports_writes_is_false(self, patch_notion) -> None:
        source = NotionSource(_config())
        assert source.supports_writes is False


class TestMaterialize:
    @pytest.mark.asyncio
    async def test_writes_pages_as_markdown_files(
        self, patch_notion, tmp_path: Path
    ) -> None:
        fake = patch_notion
        fake.search_pages.return_value = [
            _page("aaa", "Alpha"),
            _page("bbb", "Beta"),
        ]
        fake.get_page.side_effect = lambda pid: _page(pid, f"Page {pid}")
        fake.get_all_blocks.side_effect = lambda pid: [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": f"body-{pid}"}]},
            }
        ]
        source = NotionSource(_config())
        cache = tmp_path / "cache"
        stats = await source.materialize_to_vault(cache)
        assert stats.documents_seen == 2
        assert stats.documents_written == 2
        # Filenames derive from titles.
        files = sorted(p.name for p in cache.iterdir())
        assert any(name.startswith("Alpha") for name in files)
        assert any(name.startswith("Beta") for name in files)


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self, patch_notion) -> None:
        fake = patch_notion
        fake.test_connection.return_value = True
        source = NotionSource(_config())
        health = await source.health()
        assert health.status is SourceHealthStatus.OK

    @pytest.mark.asyncio
    async def test_health_failed_when_probe_returns_false(
        self, patch_notion
    ) -> None:
        fake = patch_notion
        fake.test_connection.return_value = False
        source = NotionSource(_config())
        health = await source.health()
        assert health.status is SourceHealthStatus.FAILED

    @pytest.mark.asyncio
    async def test_health_failed_on_missing_token(
        self, monkeypatch
    ) -> None:
        monkeypatch.delenv("NOTION_API_TOKEN", raising=False)
        config = SourceConfig(
            source_id="x",
            kind=SourceKind.NOTION,
            display_name="x",
            params={},
        )
        source = NotionSource(config)
        health = await source.health()
        assert health.status is SourceHealthStatus.FAILED


class TestMissingNotionClient:
    def test_clear_error_when_module_missing(self, monkeypatch) -> None:
        import sys

        # Pretend the integration module fails to import.
        original = sys.modules.get("memograph.integrations.notion.client")
        monkeypatch.setitem(
            sys.modules, "memograph.integrations.notion.client", None
        )
        source = NotionSource(_config())
        with pytest.raises(SourceError, match="memograph\\[sources-notion\\]"):
            source._ensure_client()
        # Restore so other tests don't break.
        if original is not None:
            sys.modules["memograph.integrations.notion.client"] = original
