"""Tests for MetricsCollector and ActionLogger.

Validates metrics tracking, operation recording, action logging, and history.
"""

from datetime import datetime

import pytest

from memograph.core.action_logger import (
    Action,
    ActionLogger,
    get_action_logger,
    log_action,
)
from memograph.core.metrics import (
    MetricsCollector,
    OperationMetrics,
    get_metrics,
    reset_global_metrics,
    track_async_performance,
    track_performance,
)


class TestOperationMetrics:
    """Test OperationMetrics dataclass."""

    def test_initial_state(self):
        m = OperationMetrics()
        assert m.count == 0
        assert m.avg_duration_ms == 0.0
        assert m.error_rate == 0.0
        assert m.p95_duration_ms == 0.0
        assert m.p99_duration_ms == 0.0

    def test_record(self):
        m = OperationMetrics()
        m.record(10.0)
        m.record(20.0)
        assert m.count == 2
        assert m.avg_duration_ms == 15.0
        assert m.min_duration_ms == 10.0
        assert m.max_duration_ms == 20.0

    def test_record_with_error(self):
        m = OperationMetrics()
        m.record(10.0, success=True)
        m.record(20.0, success=False)
        assert m.error_count == 1
        assert m.error_rate == 50.0

    def test_percentiles(self):
        m = OperationMetrics()
        for i in range(100):
            m.record(float(i))
        assert m.p95_duration_ms >= 90.0
        assert m.p99_duration_ms >= 95.0

    def test_to_dict(self):
        m = OperationMetrics()
        m.record(10.0)
        d = m.to_dict()
        assert "count" in d
        assert "avg_duration_ms" in d
        assert "error_rate" in d
        assert d["min_duration_ms"] == 10.0


class TestMetricsCollector:
    """Test MetricsCollector."""

    def test_record_operation(self):
        collector = MetricsCollector()
        collector.record_operation("test_op", 15.0)
        stats = collector.get_operation_stats("test_op")
        assert stats is not None
        assert stats["count"] == 1

    def test_track_operation_context(self):
        collector = MetricsCollector()
        with collector.track_operation("tracked"):
            pass  # simulates work
        stats = collector.get_operation_stats("tracked")
        assert stats is not None
        assert stats["count"] == 1
        assert stats["avg_duration_ms"] >= 0

    def test_track_operation_with_error(self):
        collector = MetricsCollector()
        with pytest.raises(ValueError):
            with collector.track_operation("failing"):
                raise ValueError("test error")
        stats = collector.get_operation_stats("failing")
        assert stats["error_count"] == 1

    def test_get_stats(self):
        collector = MetricsCollector()
        collector.record_operation("op1", 10.0)
        collector.record_operation("op2", 20.0)
        stats = collector.get_stats()
        assert "uptime_seconds" in stats
        assert "op1" in stats["operations"]
        assert "op2" in stats["operations"]

    def test_get_summary(self):
        collector = MetricsCollector()
        collector.record_operation("op1", 10.0)
        collector.record_operation("op1", 20.0, success=False)
        summary = collector.get_summary()
        assert summary["total_operations"] == 2
        assert summary["total_errors"] == 1

    def test_reset(self):
        collector = MetricsCollector()
        collector.record_operation("op", 10.0)
        collector.reset()
        assert collector.get_operation_stats("op") is None

    def test_reset_operation(self):
        collector = MetricsCollector()
        collector.record_operation("op1", 10.0)
        collector.record_operation("op2", 20.0)
        collector.reset_operation("op1")
        stats1 = collector.get_operation_stats("op1")
        stats2 = collector.get_operation_stats("op2")
        assert stats1["count"] == 0
        assert stats2["count"] == 1

    def test_nonexistent_operation(self):
        collector = MetricsCollector()
        assert collector.get_operation_stats("nope") is None


class TestGlobalMetrics:
    """Test global metrics functions."""

    def test_get_metrics_returns_instance(self):
        m = get_metrics()
        assert isinstance(m, MetricsCollector)

    def test_get_metrics_singleton(self):
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2

    def test_reset_global(self):
        m = get_metrics()
        m.record_operation("global_op", 10.0)
        reset_global_metrics()
        assert m.get_operation_stats("global_op") is None


class TestDecorators:
    """Test performance tracking decorators."""

    def test_track_performance(self):
        @track_performance("decorated_op")
        def my_func():
            return 42

        result = my_func()
        assert result == 42
        stats = get_metrics().get_operation_stats("decorated_op")
        assert stats is not None
        assert stats["count"] >= 1

    @pytest.mark.asyncio
    async def test_track_async_performance(self):
        @track_async_performance("async_op")
        async def my_async():
            return 99

        result = await my_async()
        assert result == 99
        stats = get_metrics().get_operation_stats("async_op")
        assert stats is not None


class TestAction:
    """Test Action dataclass."""

    def test_action_creation(self):
        a = Action(
            memory_id="m1",
            action_type="create",
            summary="Created",
            timestamp="2024-01-01T00:00:00",
        )
        assert a.metadata == {}
        assert a.user is None

    def test_action_to_dict(self):
        a = Action(
            memory_id="m1",
            action_type="update",
            summary="Updated",
            timestamp="2024-01-01T00:00:00",
            metadata={"key": "val"},
        )
        d = a.to_dict()
        assert d["memory_id"] == "m1"
        assert d["action_type"] == "update"
        assert d["metadata"]["key"] == "val"


class TestActionLogger:
    """Test ActionLogger."""

    def test_log_and_retrieve(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        logger.log_action("m1", "create", "Created memory")
        recent = logger.get_recent_actions(limit=10)
        assert len(recent) == 1
        assert recent[0]["memory_id"] == "m1"

    def test_filter_by_type(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        logger.log_action("m1", "create", "Created")
        logger.log_action("m1", "update", "Updated")
        creates = logger.get_recent_actions(action_type="create")
        assert len(creates) == 1

    def test_filter_by_memory(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        logger.log_action("m1", "create", "Created m1")
        logger.log_action("m2", "create", "Created m2")
        m1_actions = logger.get_recent_actions(memory_id="m1")
        assert len(m1_actions) == 1

    def test_get_memory_history(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        logger.log_action("m1", "create", "Created")
        logger.log_action("m1", "update", "Updated")
        history = logger.get_memory_history("m1")
        assert len(history) == 2

    def test_get_stats(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        logger.log_action("m1", "create", "Created")
        logger.log_action("m2", "create", "Created")
        logger.log_action("m1", "update", "Updated")
        stats = logger.get_stats()
        assert stats["total_actions"] == 3
        assert stats["unique_memories"] == 2
        assert stats["by_type"]["create"] == 2

    def test_stats_empty(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        stats = logger.get_stats()
        assert stats["total_actions"] == 0

    def test_clear_history(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        logger.log_action("m1", "create", "Created")
        logger.clear_history()
        assert len(logger.get_recent_actions()) == 0

    def test_clear_history_before_date(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        logger.log_action("m1", "create", "Old")
        cutoff = datetime.now()
        logger.log_action("m2", "create", "New")
        logger.clear_history(before_date=cutoff)
        remaining = logger.get_recent_actions()
        assert len(remaining) == 1

    def test_group_consecutive(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        now = datetime.now()
        actions = [
            {"memory_id": "m1", "action_type": "update", "timestamp": now.isoformat()},
            {"memory_id": "m1", "action_type": "tag", "timestamp": now.isoformat()},
            {"memory_id": "m2", "action_type": "create", "timestamp": now.isoformat()},
        ]
        grouped = logger.group_consecutive_actions(actions)
        assert len(grouped) == 2  # m1 group + m2 group

    def test_group_empty(self, tmp_path):
        logger = ActionLogger(str(tmp_path / "vault"))
        assert logger.group_consecutive_actions([]) == []


class TestGlobalActionLogger:
    """Test global action logger functions."""

    def test_log_action_convenience(self, tmp_path):
        vault = str(tmp_path / "vault")
        action = log_action(vault, "m1", "create", "Created")
        assert action.memory_id == "m1"

    def test_get_action_logger(self, tmp_path):
        vault = str(tmp_path / "vault")
        logger = get_action_logger(vault)
        assert isinstance(logger, ActionLogger)
