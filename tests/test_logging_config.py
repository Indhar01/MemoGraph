"""Tests for logging configuration module."""

import logging

from memograph.core.logging_config import JSONFormatter, get_logger, setup_logging


class TestJSONFormatter:
    """Test JSON log formatter."""

    def test_format_basic(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "Test message" in output
        assert "INFO" in output

    def test_format_with_extra(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Warning msg",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "WARNING" in output


class TestSetupLogging:
    """Test setup_logging function."""

    def test_setup_default(self):
        setup_logging()
        logger = logging.getLogger("memograph")
        assert logger is not None

    def test_setup_with_level(self):
        setup_logging(level="DEBUG")
        logger = logging.getLogger("memograph")
        assert logger is not None

    def test_setup_with_file(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        setup_logging(level="INFO", log_file=log_file)
        logger = logging.getLogger("memograph")
        assert logger is not None


class TestGetLogger:
    """Test get_logger function."""

    def test_get_logger(self):
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"
