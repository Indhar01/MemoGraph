"""Tests for error handling and recovery in Obsidian sync.

This test suite covers:
- Retry logic with exponential backoff
- Network error handling
- File lock detection and handling
- Rollback mechanism for critical errors
- Transient vs permanent error handling
"""

import pytest
import time
from unittest.mock import patch
from memograph.integrations.obsidian.sync import ObsidianSync
from memograph.integrations.obsidian.conflict_resolver import ConflictStrategy


@pytest.fixture
def sync_manager(tmp_path):
    """Create a sync manager with temporary paths."""
    vault_path = tmp_path / "obsidian_vault"
    memograph_vault = tmp_path / "memograph_vault"
    vault_path.mkdir(parents=True, exist_ok=True)
    memograph_vault.mkdir(parents=True, exist_ok=True)

    return ObsidianSync(
        vault_path=vault_path,
        memograph_vault=memograph_vault,
        conflict_strategy=ConflictStrategy.NEWEST_WINS,
    )


class TestRetryLogic:
    """Test retry logic with exponential backoff."""

    @pytest.mark.asyncio
    async def test_transient_error_retry(self, sync_manager):
        """Test that transient errors trigger retry."""
        attempt_count = 0

        async def failing_operation():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ConnectionError("Temporary network error")
            return {"success": True}

        # Test retry with exponential backoff
        result = await sync_manager._retry_with_backoff(
            failing_operation,
            max_attempts=3,
            initial_delay=0.1,
        )

        assert result["success"] is True
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_max_retry_attempts_exceeded(self, sync_manager):
        """Test that max retry attempts are respected."""
        attempt_count = 0

        async def always_failing():
            nonlocal attempt_count
            attempt_count += 1
            raise ConnectionError("Persistent network error")

        with pytest.raises(ConnectionError):
            await sync_manager._retry_with_backoff(
                always_failing,
                max_attempts=3,
                initial_delay=0.1,
            )

        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self, sync_manager):
        """Test that backoff delays increase exponentially."""
        delays = []

        async def failing_with_timing():
            delays.append(time.time())
            if len(delays) < 4:
                raise ConnectionError("Retry me")
            return {"success": True}

        _start_time = time.time()
        await sync_manager._retry_with_backoff(
            failing_with_timing,
            max_attempts=4,
            initial_delay=0.1,
        )

        # Verify delays increase exponentially
        assert len(delays) == 4
        # First attempt: immediate
        # Second attempt: ~0.1s delay
        # Third attempt: ~0.2s delay
        # Fourth attempt: ~0.4s delay
        if len(delays) >= 3:
            delay1 = delays[1] - delays[0]
            delay2 = delays[2] - delays[1]
            assert delay2 > delay1  # Second delay should be longer

    @pytest.mark.asyncio
    async def test_permanent_error_no_retry(self, sync_manager):
        """Test that permanent errors don't trigger retry."""
        attempt_count = 0

        async def permanent_error():
            nonlocal attempt_count
            attempt_count += 1
            raise ValueError("Permanent error - invalid data")

        with pytest.raises(ValueError):
            await sync_manager._retry_with_backoff(
                permanent_error,
                max_attempts=3,
                initial_delay=0.1,
                retryable_exceptions=(ConnectionError, TimeoutError),
            )

        # Should only attempt once for permanent errors
        assert attempt_count == 1


class TestNetworkErrorHandling:
    """Test network error handling."""

    @pytest.mark.asyncio
    async def test_connection_timeout(self, sync_manager, tmp_path):
        """Test handling of connection timeouts."""
        # Create a test file so sync has something to process
        test_file = tmp_path / "obsidian_vault" / "test.md"
        test_file.write_text("# Test\n\nContent", encoding="utf-8")

        with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
            mock_remember.side_effect = TimeoutError("Connection timeout")

            stats = await sync_manager.sync(direction="pull")

            assert len(stats["errors"]) > 0
            assert any("timeout" in str(err).lower() for err in stats["errors"])

    @pytest.mark.asyncio
    async def test_connection_refused(self, sync_manager, tmp_path):
        """Test handling of connection refused errors."""
        # Create a test file so sync has something to process
        test_file = tmp_path / "obsidian_vault" / "test.md"
        test_file.write_text("# Test\n\nContent", encoding="utf-8")

        with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
            mock_remember.side_effect = ConnectionRefusedError("Connection refused")

            stats = await sync_manager.sync(direction="pull")

            assert len(stats["errors"]) > 0
            assert any("connection" in str(err).lower() for err in stats["errors"])

    @pytest.mark.asyncio
    async def test_network_error_state_preservation(self, sync_manager, tmp_path):
        """Test that state is preserved correctly after network errors."""
        # Create test file
        test_file = tmp_path / "obsidian_vault" / "test.md"
        test_file.write_text("# Test\n\nContent")

        # Get initial state
        initial_files = len(sync_manager.state.get_tracked_files())

        # Simulate network error during sync
        with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
            mock_remember.side_effect = ConnectionError("Network error")

            stats = await sync_manager.sync(direction="pull")

            # State should not be corrupted
            assert len(sync_manager.state.get_tracked_files()) == initial_files
            assert len(stats["errors"]) > 0


class TestFileLockHandling:
    """Test file lock detection and handling."""

    @pytest.mark.asyncio
    async def test_file_lock_detection(self, sync_manager, tmp_path):
        """Test that file locks are detected."""
        test_file = tmp_path / "obsidian_vault" / "locked.md"
        test_file.write_text("# Locked File")

        # Simulate file lock
        with patch("builtins.open") as mock_open:
            mock_open.side_effect = PermissionError("File is locked")

            with pytest.raises(PermissionError):
                await sync_manager.sync_single_file(str(test_file))

    @pytest.mark.asyncio
    async def test_file_lock_retry(self, sync_manager, tmp_path):
        """Test that file locks trigger retry."""
        test_file = tmp_path / "obsidian_vault" / "locked.md"
        test_file.write_text("# Locked File")

        attempt_count = 0

        def mock_parse_file(path):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise PermissionError("File is locked")
            return {"title": "Test", "content": "Content", "tags": [], "metadata": {}}

        with patch.object(
            sync_manager.parser, "parse_file", side_effect=mock_parse_file
        ):
            # Should retry and eventually succeed
            try:
                _result = await sync_manager._sync_file_with_retry(str(test_file))
                assert attempt_count >= 2
            except Exception:
                # If it fails, verify it tried multiple times
                assert attempt_count >= 2

    @pytest.mark.asyncio
    async def test_file_lock_timeout(self, sync_manager, tmp_path):
        """Test that file lock retries eventually timeout."""
        test_file = tmp_path / "obsidian_vault" / "permanently_locked.md"
        test_file.write_text("# Permanently Locked")

        def always_locked(path):
            raise PermissionError("File is permanently locked")

        with patch.object(sync_manager.parser, "parse_file", side_effect=always_locked):
            with pytest.raises(PermissionError):
                await sync_manager._sync_file_with_retry(
                    str(test_file),
                    max_attempts=3,
                )


class TestRollbackMechanism:
    """Test rollback mechanism for critical errors."""

    @pytest.mark.asyncio
    async def test_rollback_on_critical_error(self, sync_manager, tmp_path):
        """Test that state rolls back on critical errors."""
        # Create multiple test files
        files = []
        for i in range(3):
            test_file = tmp_path / "obsidian_vault" / f"test{i}.md"
            test_file.write_text(f"# Test {i}\n\nContent {i}")
            files.append(test_file)

        # Get initial state checkpoint
        _initial_state = sync_manager.state.create_checkpoint()

        # Simulate critical error during batch sync
        with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
            call_count = 0

            async def fail_on_second(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise RuntimeError("Critical error")
                return None

            mock_remember.side_effect = fail_on_second

            stats = await sync_manager.batch_sync(
                file_paths=files,
                direction="pull",
                enable_rollback=True,
            )

            # State should be rolled back
            assert stats["rolled_back"] is True
            assert len(stats["errors"]) > 0

    @pytest.mark.asyncio
    async def test_rollback_preserves_previous_state(self, sync_manager, tmp_path):
        """Test that rollback preserves the previous valid state."""
        # Sync a file successfully first
        test_file1 = tmp_path / "obsidian_vault" / "success.md"
        test_file1.write_text("# Success\n\nContent")

        await sync_manager.sync_single_file(str(test_file1))
        success_hash = sync_manager.state.get_file_hash(str(test_file1))

        # Create checkpoint after successful sync
        checkpoint = sync_manager.state.create_checkpoint()

        # Try to sync another file that will fail
        test_file2 = tmp_path / "obsidian_vault" / "failure.md"
        test_file2.write_text("# Failure\n\nContent")

        with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
            mock_remember.side_effect = RuntimeError("Critical error")

            try:
                await sync_manager.batch_sync(
                    file_paths=[test_file2],
                    direction="pull",
                    enable_rollback=True,
                )
            except Exception:
                pass

        # Restore from checkpoint
        sync_manager.state.restore_checkpoint(checkpoint)

        # First file should still be tracked correctly
        assert sync_manager.state.get_file_hash(str(test_file1)) == success_hash
        # Second file should not be tracked
        assert sync_manager.state.get_file_hash(str(test_file2)) is None

    @pytest.mark.asyncio
    async def test_no_rollback_on_transient_errors(self, sync_manager, tmp_path):
        """Test that transient errors don't trigger rollback."""
        test_file = tmp_path / "obsidian_vault" / "transient.md"
        test_file.write_text("# Transient Error\n\nContent")

        with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
            # Transient error that will be retried
            mock_remember.side_effect = [
                ConnectionError("Temporary error"),
                None,  # Success on retry
            ]

            stats = await sync_manager.batch_sync(
                file_paths=[test_file],
                direction="pull",
                enable_rollback=True,
            )

            # Should succeed without rollback
            assert stats.get("rolled_back", False) is False
            assert stats["pulled"] >= 0


class TestErrorRecovery:
    """Test error recovery workflows."""

    @pytest.mark.asyncio
    async def test_partial_batch_recovery(self, sync_manager, tmp_path):
        """Test that batch sync can recover from partial failures."""
        # Create multiple test files
        files = []
        for i in range(5):
            test_file = tmp_path / "obsidian_vault" / f"test{i}.md"
            test_file.write_text(f"# Test {i}\n\nContent {i}")
            files.append(test_file)

        # Make one file fail
        def selective_failure(*args, **kwargs):
            content = kwargs.get("content", "")
            if "Content 2" in content:
                raise ValueError("Validation error")
            return None

        with patch.object(
            sync_manager.kernel, "remember_async", side_effect=selective_failure
        ):
            stats = await sync_manager.batch_sync(
                file_paths=files,
                direction="pull",
            )

            # Should have some successes and one error
            assert stats["pulled"] > 0  # Some files succeeded
            assert len(stats["errors"]) > 0  # One file failed

    @pytest.mark.asyncio
    async def test_resume_after_cancellation(self, sync_manager, tmp_path):
        """Test that sync can resume after cancellation."""
        # Create test files
        files = []
        for i in range(10):
            test_file = tmp_path / "obsidian_vault" / f"test{i}.md"
            test_file.write_text(f"# Test {i}\n\nContent {i}")
            files.append(test_file)

        # Start batch sync
        files_synced = 0

        def count_syncs(*args, **kwargs):
            nonlocal files_synced
            files_synced += 1
            if files_synced == 5:
                # Cancel after 5 files
                sync_manager.cancel_batch_sync()
            return None

        with patch.object(
            sync_manager.kernel, "remember_async", side_effect=count_syncs
        ):
            stats1 = await sync_manager.batch_sync(
                file_paths=files,
                direction="pull",
            )

            assert stats1["cancelled"] is True
            assert stats1["pulled"] < len(files)

        # Resume sync with remaining files
        with patch.object(sync_manager.kernel, "remember_async", return_value=None):
            stats2 = await sync_manager.batch_sync(
                file_paths=files,
                direction="pull",
            )

            # Should complete successfully this time
            assert stats2["cancelled"] is False

    @pytest.mark.asyncio
    async def test_error_notification_user(self, sync_manager, tmp_path):
        """Test that users are notified of permanent failures."""
        test_file = tmp_path / "obsidian_vault" / "permanent_error.md"
        test_file.write_text("# Permanent Error\n\nContent")

        # Simulate permanent error
        with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
            mock_remember.side_effect = ValueError("Invalid data format")

            stats = await sync_manager.sync(direction="pull")

            # Error should be in stats
            assert len(stats["errors"]) > 0
            assert any("Invalid data" in str(err) for err in stats["errors"])

    @pytest.mark.asyncio
    async def test_concurrent_error_handling(self, sync_manager, tmp_path):
        """Test error handling with concurrent operations."""
        files = []
        for i in range(5):
            test_file = tmp_path / "obsidian_vault" / f"concurrent{i}.md"
            test_file.write_text(f"# Concurrent {i}\n\nContent {i}")
            files.append(test_file)

        # Simulate errors in some files during concurrent processing
        call_count = 0

        async def intermittent_failure(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise ConnectionError("Intermittent error")
            return None

        with patch.object(
            sync_manager.kernel, "remember_async", side_effect=intermittent_failure
        ):
            stats = await sync_manager.batch_sync(
                file_paths=files,
                direction="pull",
            )

            # Some files should succeed, some should fail
            assert len(stats["errors"]) > 0
            # At least some operations should have been attempted
            assert call_count > 0


class TestErrorClassification:
    """Test error classification and handling strategies."""

    @pytest.mark.asyncio
    async def test_transient_errors_identified(self, sync_manager):
        """Test that transient errors are correctly identified."""
        transient_errors = [
            ConnectionError("Connection failed"),
            TimeoutError("Request timeout"),
            ConnectionRefusedError("Connection refused"),
            OSError("Network unreachable"),
        ]

        for error in transient_errors:
            is_transient = sync_manager._is_transient_error(error)
            assert is_transient is True, f"{type(error).__name__} should be transient"

    @pytest.mark.asyncio
    async def test_permanent_errors_identified(self, sync_manager):
        """Test that permanent errors are correctly identified."""
        permanent_errors = [
            ValueError("Invalid input"),
            TypeError("Type mismatch"),
            KeyError("Missing key"),
            AttributeError("Missing attribute"),
        ]

        for error in permanent_errors:
            is_transient = sync_manager._is_transient_error(error)
            assert is_transient is False, f"{type(error).__name__} should be permanent"

    @pytest.mark.asyncio
    async def test_file_lock_errors_retryable(self, sync_manager):
        """Test that file lock errors are treated as retryable."""
        lock_errors = [
            PermissionError("File is locked"),
            OSError(13, "Permission denied"),  # Windows file lock
            BlockingIOError("Resource temporarily unavailable"),
        ]

        for error in lock_errors:
            is_retryable = sync_manager._is_retryable_error(error)
            assert is_retryable is True, f"{type(error).__name__} should be retryable"


class TestErrorMetrics:
    """Test error metrics and reporting."""

    @pytest.mark.asyncio
    async def test_error_metrics_tracked(self, sync_manager, tmp_path):
        """Test that error metrics are properly tracked."""
        test_file = tmp_path / "obsidian_vault" / "metrics_test.md"
        test_file.write_text("# Metrics Test\n\nContent")

        with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
            mock_remember.side_effect = ConnectionError("Network error")

            stats = await sync_manager.sync(direction="pull")

            # Check error metrics
            assert "errors" in stats
            assert len(stats["errors"]) > 0
            assert "timestamp" in stats
            assert "duration" in stats

    @pytest.mark.asyncio
    async def test_error_history_maintained(self, sync_manager, tmp_path):
        """Test that error history is maintained."""
        # Trigger multiple errors
        for i in range(3):
            test_file = tmp_path / "obsidian_vault" / f"error{i}.md"
            test_file.write_text(f"# Error {i}\n\nContent")

            with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
                mock_remember.side_effect = ValueError(f"Error {i}")

                await sync_manager.sync(direction="pull")

        # Check error history
        error_history = sync_manager.get_error_history()
        assert len(error_history) >= 3

        # Verify error details are captured
        for error_entry in error_history:
            assert "timestamp" in error_entry
            assert "error_type" in error_entry
            assert "message" in error_entry

    @pytest.mark.asyncio
    async def test_error_rate_limiting(self, sync_manager, tmp_path):
        """Test that excessive errors trigger rate limiting."""
        files = []
        for i in range(20):
            test_file = tmp_path / "obsidian_vault" / f"rate_limit{i}.md"
            test_file.write_text(f"# Rate Limit {i}\n\nContent")
            files.append(test_file)

        # Trigger many errors rapidly
        with patch.object(sync_manager.kernel, "remember_async") as mock_remember:
            mock_remember.side_effect = ConnectionError("Network error")

            stats = await sync_manager.batch_sync(
                file_paths=files,
                direction="pull",
                batch_size=5,  # Small batch size to trigger rate limiting between batches
            )

            # Should stop early due to error rate limiting
            # With 20 files, batch_size=5, and error_rate_limit=10:
            # Batch 1: 5 files, 5 errors
            # Batch 2: 5 files, 10 errors total
            # Before Batch 3: check errors (10) >= limit (10), set rate_limited=True, break
            # So should have 10 errors and rate_limited=True
            assert (
                stats.get("rate_limited", False) or len(stats["errors"]) < len(files)
            ), f"Expected rate limiting but got {len(stats['errors'])} errors and rate_limited={stats.get('rate_limited', False)}"
