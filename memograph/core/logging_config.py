"""
Production-grade logging configuration for MemoGraph.

This module provides structured logging with configurable levels,
rotation, and formatting for production environments.

Example:
    >>> from memograph.core.logging_config import setup_logging, get_logger
    >>>
    >>> # Setup logging for production
    >>> setup_logging(
    ...     level="INFO",
    ...     log_file="memograph.log",
    ...     rotation_size_mb=10,
    ...     backup_count=5
    ... )
    >>>
    >>> # Get logger for your module
    >>> logger = get_logger(__name__)
    >>> logger.info("Memory operation started", extra={"memory_id": "123"})
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON string representation of log record
        """
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_data.update(record.extra_fields)

        # Add any custom attributes
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "extra_fields",
                "message",
                "asctime",
            ]:
                log_data[key] = value

        return json.dumps(log_data)


class ContextFilter(logging.Filter):
    """Filter to add context information to log records."""

    def __init__(self, context: dict[str, Any] | None = None):
        """Initialize context filter.

        Args:
            context: Context dictionary to add to all log records
        """
        super().__init__()
        self.context = context or {}

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context to log record.

        Args:
            record: Log record to modify

        Returns:
            True to allow record through
        """
        if not hasattr(record, "extra_fields"):
            record.extra_fields = {}

        record.extra_fields.update(self.context)
        return True


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    rotation_size_mb: int = 10,
    backup_count: int = 5,
    json_format: bool = False,
    console_output: bool = True,
    filter_sensitive: bool = True,
) -> None:
    """Setup production-grade logging configuration.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (None for no file logging)
        rotation_size_mb: Size in MB before rotating log files
        backup_count: Number of backup files to keep
        json_format: Use JSON formatting for structured logs
        console_output: Enable console output
        filter_sensitive: Filter sensitive data from logs

    Example:
        >>> setup_logging(
        ...     level="DEBUG",
        ...     log_file="memograph.log",
        ...     json_format=True
        ... )
    """
    # Get root logger for memograph
    root_logger = logging.getLogger("memograph")
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create formatters
    formatter: logging.Formatter
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))
        console_handler.setFormatter(formatter)

        if filter_sensitive:
            console_handler.addFilter(SensitiveDataFilter())

        root_logger.addHandler(console_handler)

    # File handler with rotation
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=rotation_size_mb * 1024 * 1024,  # Convert MB to bytes
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, level.upper()))
        file_handler.setFormatter(formatter)

        if filter_sensitive:
            file_handler.addFilter(SensitiveDataFilter())

        root_logger.addHandler(file_handler)

    # Prevent propagation to avoid duplicate logs
    root_logger.propagate = False


class SensitiveDataFilter(logging.Filter):
    """Filter to redact sensitive data from log messages."""

    SENSITIVE_PATTERNS = [
        "password",
        "token",
        "api_key",
        "secret",
        "auth",
        "credentials",
        "private_key",
        "access_token",
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive data from log record.

        Args:
            record: Log record to filter

        Returns:
            True to allow record through
        """
        # Redact sensitive data in message
        message = record.getMessage().lower()

        for pattern in self.SENSITIVE_PATTERNS:
            if pattern in message:
                record.msg = record.msg.replace(
                    record.msg, f"[REDACTED: contains {pattern}]"
                )

        return True


def get_logger(name: str, context: dict[str, Any] | None = None) -> logging.Logger:
    """Get a logger with optional context.

    Args:
        name: Logger name (usually __name__)
        context: Optional context dictionary to add to all logs

    Returns:
        Configured logger instance

    Example:
        >>> logger = get_logger(__name__, context={"vault": "production"})
        >>> logger.info("Operation completed", extra={"duration_ms": 123})
    """
    logger = logging.getLogger(name)

    if context:
        logger.addFilter(ContextFilter(context))

    return logger


def log_performance(
    logger: logging.Logger, operation: str, duration_ms: float, **kwargs
) -> None:
    """Log performance metrics in a structured way.

    Args:
        logger: Logger instance
        operation: Operation name
        duration_ms: Duration in milliseconds
        **kwargs: Additional performance metrics

    Example:
        >>> logger = get_logger(__name__)
        >>> log_performance(
        ...     logger,
        ...     "retrieve_nodes",
        ...     duration_ms=123.45,
        ...     result_count=10,
        ...     cache_hit=True
        ... )
    """
    perf_data = {"operation": operation, "duration_ms": duration_ms, **kwargs}

    logger.info(f"Performance: {operation}", extra={"performance": perf_data})


def log_error(
    logger: logging.Logger,
    error: Exception,
    operation: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Log error with context in a structured way.

    Args:
        logger: Logger instance
        error: Exception that occurred
        operation: Operation that failed
        context: Additional context about the error

    Example:
        >>> logger = get_logger(__name__)
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     log_error(logger, e, "risky_operation", {"param": "value"})
    """
    error_data = {
        "operation": operation,
        "error_type": type(error).__name__,
        "error_message": str(error),
        **(context or {}),
    }

    logger.error(
        f"Error in {operation}: {str(error)}",
        exc_info=True,
        extra={"error_details": error_data},
    )


# Default configuration
_default_configured = False


def ensure_default_logging():
    """Ensure default logging is configured."""
    global _default_configured

    if not _default_configured:
        setup_logging(level="INFO", console_output=True, json_format=False)
        _default_configured = True


# Configure default logging on import
ensure_default_logging()
