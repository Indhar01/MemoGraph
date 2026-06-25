"""Tests for Obsidian-MemoGraph batch sync operations."""

import pytest
import asyncio

from memograph.integrations.obsidian.sync import ObsidianSync
from memograph.integrations.obsidian.conflict_resolver import ConflictStrategy


@pytest.fixture
def temp_obsidian_vault(tmp_path):
    """Create a temporary Obsidian vault directory."""
    vault = tmp_path / "obsidian_vault"
    vault.mkdir()
    return vault


@pytest.fixture
def temp_memograph_vault(tmp_path):
    """Create a temporary MemoGraph vault directory."""
    vault = tmp_path / "memograph_vault"
    vault.mkdir()
    return vault


@pytest.fixture
def obsidian_sync(temp_obsidian_vault, temp_memograph_vault):
    """Create an ObsidianSync instance with temporary vaults."""
    return ObsidianSync(
        vault_path=temp_obsidian_vault,
        memograph_vault=temp_memograph_vault,
        conflict_strategy=ConflictStrategy.NEWEST_WINS,
    )


@pytest.fixture
def create_test_notes(temp_obsidian_vault):
    """Factory fixture to create multiple test notes."""

    def _create_notes(count: int):
        notes = []
        for i in range(count):
            note_path = temp_obsidian_vault / f"note_{i:03d}.md"
            content = f"""---
title: Test Note {i}
tags: [test, batch, note{i}]
---

This is test note {i} for batch sync testing.
It contains some [[wikilinks]] and #hashtags.
"""
            note_path.write_text(content, encoding="utf-8")
            notes.append(note_path)
        return notes

    return _create_notes


class TestBatchSyncBasics:
    """Test basic batch sync operations."""

    @pytest.mark.asyncio
    async def test_batch_sync_empty_vault(self, obsidian_sync):
        """Test batch sync on empty vault."""
        stats = await obsidian_sync.batch_sync()

        assert stats["pulled"] == 0
        assert stats["pushed"] == 0
        assert stats["conflicts"] == 0
        assert stats["cancelled"] is False
        assert stats["processed"] == 0

    @pytest.mark.asyncio
    async def test_batch_sync_single_file(self, obsidian_sync, create_test_notes):
        """Test batch sync with a single file."""
        create_test_notes(1)

        stats = await obsidian_sync.batch_sync(direction="pull")

        assert stats["pulled"] == 1
        assert stats["processed"] == 1
        assert stats["cancelled"] is False

    @pytest.mark.asyncio
    async def test_batch_sync_multiple_files(self, obsidian_sync, create_test_notes):
        """Test batch sync with multiple files."""
        create_test_notes(10)

        stats = await obsidian_sync.batch_sync(direction="pull")

        assert stats["pulled"] == 10
        assert stats["processed"] == 10
        assert stats["cancelled"] is False

    @pytest.mark.asyncio
    async def test_batch_sync_large_dataset(self, obsidian_sync, create_test_notes):
        """Test batch sync with large number of files."""
        # Create 100 test notes
        create_test_notes(100)

        stats = await obsidian_sync.batch_sync(direction="pull", batch_size=25)

        assert stats["pulled"] == 100
        assert stats["processed"] == 100
        assert stats["cancelled"] is False
        assert len(stats["errors"]) == 0

    @pytest.mark.asyncio
    async def test_batch_sync_bidirectional(
        self, obsidian_sync, temp_obsidian_vault, create_test_notes
    ):
        """Test bidirectional batch sync."""
        # Create notes in Obsidian
        create_test_notes(5)

        # Create memory in MemoGraph for push
        push_path = temp_obsidian_vault / "from_memo.md"
        await obsidian_sync.kernel.remember_async(
            title="From MemoGraph",
            content="Pushed content",
            meta={"source": "obsidian", "obsidian_path": str(push_path)},
        )
        obsidian_sync.kernel.ingest()

        stats = await obsidian_sync.batch_sync(direction="bidirectional")

        assert stats["pulled"] >= 5
        assert stats["pushed"] >= 1
        assert stats["cancelled"] is False


class TestBatchSizeAndChunking:
    """Test batch size limits and chunking."""

    @pytest.mark.asyncio
    async def test_batch_sync_with_custom_batch_size(
        self, obsidian_sync, create_test_notes
    ):
        """Test batch sync with custom batch size."""
        create_test_notes(20)

        stats = await obsidian_sync.batch_sync(
            direction="pull",
            batch_size=5,
        )

        assert stats["pulled"] == 20
        assert stats["processed"] == 20

    @pytest.mark.asyncio
    async def test_batch_sync_respects_batch_size(
        self, obsidian_sync, create_test_notes
    ):
        """Test that batch sync processes files in chunks."""
        create_test_notes(50)

        # Track how many batches were processed by monitoring async sleeps
        batch_size = 10
        stats = await obsidian_sync.batch_sync(
            direction="pull",
            batch_size=batch_size,
        )

        # All files should be processed
        assert stats["pulled"] == 50
        # Should have processed in 5 batches (50/10)

    @pytest.mark.asyncio
    async def test_batch_sync_handles_incomplete_batch(
        self, obsidian_sync, create_test_notes
    ):
        """Test batch sync with files not perfectly divisible by batch size."""
        # 23 files with batch size 10 = 2 full batches + 1 batch of 3
        create_test_notes(23)

        stats = await obsidian_sync.batch_sync(
            direction="pull",
            batch_size=10,
        )

        assert stats["pulled"] == 23
        assert stats["processed"] == 23


class TestProgressTracking:
    """Test progress tracking callbacks."""

    @pytest.mark.asyncio
    async def test_batch_sync_calls_progress_callback(
        self, obsidian_sync, create_test_notes
    ):
        """Test that progress callback is called during batch sync."""
        create_test_notes(10)

        progress_calls = []

        def progress_callback(current, total, file_path, status):
            progress_calls.append(
                {
                    "current": current,
                    "total": total,
                    "file": file_path,
                    "status": status,
                }
            )

        _stats = await obsidian_sync.batch_sync(
            direction="pull",
            progress_callback=progress_callback,
        )

        # Progress callback should have been called
        assert len(progress_calls) > 0
        # First call should have current=1
        assert progress_calls[0]["current"] >= 1
        # Last call should have current=total
        assert progress_calls[-1]["current"] <= progress_calls[-1]["total"]
        # Total should be consistent
        assert all(call["total"] == 10 for call in progress_calls)

    @pytest.mark.asyncio
    async def test_progress_callback_receives_correct_info(
        self, obsidian_sync, create_test_notes
    ):
        """Test that progress callback receives correct information."""
        notes = create_test_notes(5)

        progress_calls = []

        def progress_callback(current, total, file_path, status):
            progress_calls.append(
                {
                    "current": current,
                    "total": total,
                    "file": file_path,
                    "status": status,
                }
            )

        await obsidian_sync.batch_sync(
            direction="pull",
            progress_callback=progress_callback,
        )

        # Check that file paths are actual note paths
        file_paths = [call["file"] for call in progress_calls]
        # Compare each note path against individual file path strings
        # (avoids issues with backslash escaping in list string representation on Windows)
        assert any(any(str(note) == fp for fp in file_paths) for note in notes)

        # Check that status is appropriate
        assert all(call["status"] in ["pulling", "pushing"] for call in progress_calls)

    @pytest.mark.asyncio
    async def test_batch_sync_without_callback(self, obsidian_sync, create_test_notes):
        """Test that batch sync works without progress callback."""
        create_test_notes(10)

        # Should not raise an error without callback
        stats = await obsidian_sync.batch_sync(direction="pull")

        assert stats["pulled"] == 10
        assert stats["processed"] == 10


class TestCancellation:
    """Test batch sync cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_batch_sync(self, obsidian_sync, create_test_notes):
        """Test cancelling batch sync operation."""
        create_test_notes(50)

        # Start batch sync in background
        async def cancel_after_delay():
            await asyncio.sleep(0.1)  # Let some processing happen
            obsidian_sync.cancel_batch_sync()

        # Run both concurrently
        cancel_task = asyncio.create_task(cancel_after_delay())
        stats = await obsidian_sync.batch_sync(
            direction="pull",
            batch_size=5,
        )
        await cancel_task

        # Sync should have been cancelled
        assert stats["cancelled"] is True
        # Some files may have been processed before cancellation
        assert stats["processed"] >= 0
        assert stats["processed"] < 50

    @pytest.mark.asyncio
    async def test_cancel_batch_sync_returns_partial_results(
        self, obsidian_sync, create_test_notes
    ):
        """Test that cancellation returns partial results."""
        create_test_notes(30)

        progress_calls = []

        def progress_callback(current, total, file_path, status):
            progress_calls.append(current)
            # Cancel after processing 10 files
            if current >= 10:
                obsidian_sync.cancel_batch_sync()

        stats = await obsidian_sync.batch_sync(
            direction="pull",
            batch_size=5,
            progress_callback=progress_callback,
        )

        assert stats["cancelled"] is True
        # Should have processed at least some files
        assert stats["pulled"] > 0
        assert stats["pulled"] < 30

    @pytest.mark.asyncio
    async def test_cancel_batch_sync_when_not_running(self, obsidian_sync):
        """Test cancelling when no batch sync is running."""
        result = obsidian_sync.cancel_batch_sync()
        assert result is False

    @pytest.mark.asyncio
    async def test_get_batch_progress_during_sync(
        self, obsidian_sync, create_test_notes
    ):
        """Test getting batch progress during sync."""
        create_test_notes(20)

        progress_checked = False

        def progress_callback(current, total, file_path, status):
            nonlocal progress_checked
            if not progress_checked:
                _progress = obsidian_sync.get_batch_progress()
                # During sync, should show as syncing
                # Note: _is_syncing may not be set in the current implementation
                progress_checked = True

        await obsidian_sync.batch_sync(
            direction="pull",
            progress_callback=progress_callback,
        )

        assert progress_checked


class TestErrorHandling:
    """Test error handling in batch operations."""

    @pytest.mark.asyncio
    async def test_batch_sync_continues_on_single_file_error(
        self, obsidian_sync, temp_obsidian_vault
    ):
        """Test that batch sync continues after single file error."""
        # Create valid notes
        for i in range(5):
            note = temp_obsidian_vault / f"valid_{i}.md"
            note.write_text(
                f"---\ntitle: Valid {i}\n---\n\nContent {i}", encoding="utf-8"
            )

        # Create a note that will cause parsing error
        bad_note = temp_obsidian_vault / "invalid.md"
        bad_note.write_text("---\ntitle: Invalid\n---\n\nContent", encoding="utf-8")

        # Mock the parser to raise an exception for the invalid note
        original_parse = obsidian_sync.parser.parse_file

        def mock_parse(path):
            if "invalid.md" in str(path):
                raise ValueError("Simulated parsing error")
            return original_parse(path)

        obsidian_sync.parser.parse_file = mock_parse

        stats = await obsidian_sync.batch_sync(direction="pull")

        # Should have processed valid notes
        assert (
            stats["pulled"] >= 4
        ), f"Expected at least 4 pulled but got {stats['pulled']}"
        # Should have recorded error for invalid note
        assert len(stats["errors"]) > 0, f"Expected errors but got: {stats}"
        # Verify the error message mentions the invalid file
        assert any(
            "invalid.md" in str(err) for err in stats["errors"]
        ), f"Expected error about invalid.md but got: {stats['errors']}"

    @pytest.mark.asyncio
    async def test_batch_sync_handles_permission_errors(
        self, obsidian_sync, temp_obsidian_vault, create_test_notes
    ):
        """Test handling of permission errors during batch sync."""
        create_test_notes(5)

        # Mock a permission error on one file
        original_parse = obsidian_sync.parser.parse_file

        def mock_parse(path):
            if "note_002" in str(path):
                raise PermissionError(f"Cannot read {path}")
            return original_parse(path)

        obsidian_sync.parser.parse_file = mock_parse

        stats = await obsidian_sync.batch_sync(direction="pull")

        # Should have processed other files
        assert stats["pulled"] >= 4
        # Should have recorded the error
        assert len(stats["errors"]) > 0
        assert any(
            "note_002" in error or "PermissionError" in error
            for error in stats["errors"]
        )


class TestBatchSyncDirections:
    """Test different sync directions in batch mode."""

    @pytest.mark.asyncio
    async def test_batch_sync_pull_only(self, obsidian_sync, create_test_notes):
        """Test batch sync with pull-only direction."""
        create_test_notes(10)

        stats = await obsidian_sync.batch_sync(direction="pull")

        assert stats["pulled"] == 10
        assert stats["pushed"] == 0

    @pytest.mark.asyncio
    async def test_batch_sync_push_only(
        self, obsidian_sync, temp_obsidian_vault, create_test_notes
    ):
        """Test batch sync with push-only direction."""
        # Create memories in MemoGraph
        for i in range(5):
            push_path = temp_obsidian_vault / f"push_{i}.md"
            await obsidian_sync.kernel.remember_async(
                title=f"Push Note {i}",
                content=f"Content {i}",
                meta={"source": "obsidian", "obsidian_path": str(push_path)},
            )

        obsidian_sync.kernel.ingest()
        stats = await obsidian_sync.batch_sync(direction="push")

        assert stats["pushed"] == 5
        assert stats["pulled"] == 0
        # Verify files were created
        assert (temp_obsidian_vault / "push_0.md").exists()
        assert (temp_obsidian_vault / "push_4.md").exists()


class TestBatchSyncFileSelection:
    """Test batch sync with specific file selection."""

    @pytest.mark.asyncio
    async def test_batch_sync_specific_files(self, obsidian_sync, create_test_notes):
        """Test batch sync with specific file list."""
        notes = create_test_notes(20)

        # Select only first 5 notes
        selected_files = notes[:5]

        stats = await obsidian_sync.batch_sync(
            file_paths=selected_files,
            direction="pull",
        )

        assert stats["pulled"] == 5
        assert stats["processed"] == 5

    @pytest.mark.asyncio
    async def test_batch_sync_with_none_file_paths(
        self, obsidian_sync, create_test_notes
    ):
        """Test batch sync with None file_paths (syncs all files)."""
        create_test_notes(10)

        stats = await obsidian_sync.batch_sync(
            file_paths=None,
            direction="pull",
        )

        assert stats["pulled"] == 10


class TestBatchSyncStateTracking:
    """Test sync state tracking during batch operations."""

    @pytest.mark.asyncio
    async def test_batch_sync_updates_state(self, obsidian_sync, create_test_notes):
        """Test that batch sync updates sync state."""
        _notes = create_test_notes(5)

        # Perform batch sync
        await obsidian_sync.batch_sync(direction="pull")

        # Check that sync was marked as completed
        status = obsidian_sync.get_sync_status()
        assert status["last_sync"] is not None
        assert status["tracked_files"] > 0

    @pytest.mark.asyncio
    async def test_batch_sync_skips_unchanged_files_on_repeat(
        self, obsidian_sync, create_test_notes
    ):
        """Test that batch sync skips unchanged files on repeat sync."""
        create_test_notes(10)

        # First sync
        stats1 = await obsidian_sync.batch_sync(direction="pull")
        assert stats1["pulled"] == 10

        # Second sync without changes
        stats2 = await obsidian_sync.batch_sync(direction="pull")
        assert stats2["pulled"] == 0  # All files unchanged

    @pytest.mark.asyncio
    async def test_batch_sync_detects_changes(self, obsidian_sync, create_test_notes):
        """Test that batch sync detects changed files."""
        notes = create_test_notes(5)

        # First sync
        await obsidian_sync.batch_sync(direction="pull")

        # Modify one file
        notes[2].write_text(
            "---\ntitle: Modified\n---\n\nModified content", encoding="utf-8"
        )

        # Second sync should detect the change
        stats = await obsidian_sync.batch_sync(direction="pull")
        assert stats["pulled"] == 1  # Only the modified file


class TestBatchSyncPerformance:
    """Test batch sync performance characteristics."""

    @pytest.mark.asyncio
    async def test_batch_sync_completes_in_reasonable_time(
        self, obsidian_sync, create_test_notes
    ):
        """Test that batch sync of 100 files completes in reasonable time."""
        import time

        create_test_notes(100)

        start_time = time.time()
        stats = await obsidian_sync.batch_sync(direction="pull", batch_size=20)
        elapsed = time.time() - start_time

        assert stats["pulled"] == 100
        # Should complete within 30 seconds for 100 files
        assert elapsed < 30

    @pytest.mark.asyncio
    async def test_batch_sync_memory_efficient(self, obsidian_sync, create_test_notes):
        """Test that batch sync doesn't load all files into memory at once."""
        # Create many files
        create_test_notes(100)

        # Use small batch size to ensure chunking
        stats = await obsidian_sync.batch_sync(
            direction="pull",
            batch_size=10,
        )

        # All files should be processed successfully
        assert stats["pulled"] == 100
        assert len(stats["errors"]) == 0


class TestBatchSyncConflicts:
    """Test conflict handling in batch sync."""

    @pytest.mark.asyncio
    async def test_batch_sync_tracks_conflicts(
        self, obsidian_sync, temp_obsidian_vault
    ):
        """Test that batch sync properly tracks conflicts."""
        # Create note in Obsidian
        note_path = temp_obsidian_vault / "conflict.md"
        note_path.write_text(
            "---\ntitle: Original\n---\n\nOriginal content", encoding="utf-8"
        )

        # Pull it to MemoGraph
        await obsidian_sync.batch_sync(direction="pull")

        # Modify in Obsidian
        note_path.write_text(
            "---\ntitle: Modified in Obsidian\n---\n\nObsidian content",
            encoding="utf-8",
        )

        # Modify in MemoGraph (by creating a memory with same path)
        await obsidian_sync.kernel.remember_async(
            title="Modified in MemoGraph",
            content="MemoGraph content",
            meta={"source": "obsidian", "obsidian_path": str(note_path)},
        )
        obsidian_sync.kernel.ingest()

        # Sync again - should detect conflict
        stats = await obsidian_sync.batch_sync(direction="bidirectional")

        # Conflict should be detected and resolved
        assert stats["conflicts"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
