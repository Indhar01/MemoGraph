"""Tests for :class:`memograph.sources.local.LocalSource`."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from memograph.sources.base import (
    Document,
    DocumentEncoding,
    DocumentRef,
    SourceConfig,
    SourceError,
    SourceHealthStatus,
    SourceKind,
    SourceNotFoundError,
    SyncMode,
)
from memograph.sources.local import LocalSource


def _config(path: Path, source_id: str = "primary") -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        kind=SourceKind.LOCAL,
        display_name="Local",
        tenant_id=None,
        params={"path": str(path)},
    )


@pytest.fixture
def populated_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha", encoding="utf-8")
    (vault / "beta.md").write_text("# Beta", encoding="utf-8")
    sub = vault / "topics"
    sub.mkdir()
    (sub / "nested.md").write_text("# Nested", encoding="utf-8")
    return vault


class TestConstruction:
    def test_requires_path(self) -> None:
        bad = SourceConfig(
            source_id="x",
            kind=SourceKind.LOCAL,
            display_name="Bad",
            params={},
        )
        with pytest.raises(SourceError, match="requires params"):
            LocalSource(bad)

    def test_constructor_is_lazy(self, tmp_path: Path) -> None:
        # Nonexistent path should NOT raise on construction; only on
        # the first I/O call. This matters because the registry
        # constructs sources in dispatch loops where eager I/O would
        # block other ops.
        target = tmp_path / "not-yet"
        source = LocalSource(_config(target))
        assert source.source_id == "primary"
        assert source.kind is SourceKind.LOCAL


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_lists_top_level_and_nested(self, populated_vault: Path) -> None:
        source = LocalSource(_config(populated_vault))
        refs: list[DocumentRef] = [ref async for ref in source.list_documents()]
        ids = sorted(r.doc_id for r in refs)
        assert ids == ["alpha.md", "beta.md", "topics/nested.md"]

    @pytest.mark.asyncio
    async def test_empty_vault(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        source = LocalSource(_config(empty))
        refs = [r async for r in source.list_documents()]
        assert refs == []


class TestReadDocument:
    @pytest.mark.asyncio
    async def test_round_trip(self, populated_vault: Path) -> None:
        source = LocalSource(_config(populated_vault))
        doc = await source.read_document("alpha.md")
        assert doc.encoding is DocumentEncoding.MARKDOWN
        assert doc.content == "# Alpha"
        assert doc.ref.doc_id == "alpha.md"
        assert doc.ref.title == "alpha"

    @pytest.mark.asyncio
    async def test_missing_raises(self, populated_vault: Path) -> None:
        source = LocalSource(_config(populated_vault))
        with pytest.raises(SourceNotFoundError):
            await source.read_document("does-not-exist.md")

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, populated_vault: Path) -> None:
        source = LocalSource(_config(populated_vault))
        with pytest.raises(SourceError, match="outside the source root"):
            # Resolving "../../etc/passwd" relative to the vault
            # would escape the root; the guard catches it.
            await source.read_document("../escapes.md")


class TestWriteDocument:
    @pytest.mark.asyncio
    async def test_writes_new_file(self, populated_vault: Path) -> None:
        source = LocalSource(_config(populated_vault))
        ref = DocumentRef(
            doc_id="gamma.md",
            title="gamma",
            modified_at=datetime.now(timezone.utc),
        )
        doc = Document(ref=ref, content="# Gamma")
        result = await source.write_document(doc)
        assert result.doc_id == "gamma.md"
        assert (populated_vault / "gamma.md").read_text(encoding="utf-8") == "# Gamma"

    @pytest.mark.asyncio
    async def test_rejects_binary(self, populated_vault: Path) -> None:
        source = LocalSource(_config(populated_vault))
        ref = DocumentRef(
            doc_id="image.png",
            title="image",
            modified_at=datetime.now(timezone.utc),
        )
        doc = Document(ref=ref, content=b"\x89PNG", encoding=DocumentEncoding.BINARY)
        with pytest.raises(SourceError, match="binary"):
            await source.write_document(doc)


class TestMaterialize:
    @pytest.mark.asyncio
    async def test_same_dir_is_noop(self, populated_vault: Path) -> None:
        source = LocalSource(_config(populated_vault))
        stats = await source.materialize_to_vault(populated_vault)
        assert stats.documents_seen == 3
        assert stats.documents_written == 0
        assert stats.mode is SyncMode.FULL

    @pytest.mark.asyncio
    async def test_copies_to_different_dir(
        self, populated_vault: Path, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache"
        source = LocalSource(_config(populated_vault))
        stats = await source.materialize_to_vault(cache)
        assert stats.documents_written == 3
        assert (cache / "alpha.md").read_text(encoding="utf-8") == "# Alpha"
        # Nested structure preserved.
        assert (cache / "topics" / "nested.md").exists()


class TestHealth:
    @pytest.mark.asyncio
    async def test_healthy_when_dir_exists(self, populated_vault: Path) -> None:
        source = LocalSource(_config(populated_vault))
        health = await source.health()
        assert health.status is SourceHealthStatus.OK
        assert health.documents_total == 3

    @pytest.mark.asyncio
    async def test_failed_when_dir_missing(self, tmp_path: Path) -> None:
        # Use a path the OS reports as a file (not a dir) — _ensure_storage
        # would otherwise create the dir on first call. Easier: point
        # at a path the source caches as non-existent at health-check
        # time without creating intermediate state.
        # Strategy: bypass the storage initialization by checking the
        # constructor's resolved path against a known-missing parent.
        _missing_parent = tmp_path / "no-parent" / "vault"
        # Don't create it; the parent itself doesn't exist so VaultStorage
        # mkdir(parents=True) WILL create it. We need a different failure
        # mode: pass a path that resolves to an existing FILE, not a dir.
        file_path = tmp_path / "actually-a-file"
        file_path.write_text("not a dir")
        source = LocalSource(_config(file_path))
        health = await source.health()
        # VaultStorage construction on an existing FILE raises in mkdir;
        # health catches OSError and reports FAILED.
        assert health.status is SourceHealthStatus.FAILED
        assert health.last_error


class TestCapabilities:
    def test_supports_writes(self, tmp_path: Path) -> None:
        source = LocalSource(_config(tmp_path))
        assert source.supports_writes is True

    def test_does_not_support_watch_in_phase_1(self, tmp_path: Path) -> None:
        # LocalSource ships without watchdog integration in Phase 1.
        # Sync worker falls back to periodic polling.
        source = LocalSource(_config(tmp_path))
        assert source.supports_watch is False
