"""
Structured Error Handling for MemoGraph API

This module provides a comprehensive error handling system with:
- Structured error responses with error codes
- User-friendly messages with actionable suggestions
- Proper HTTP status codes
- Detailed logging for debugging
- Type-safe error definitions

Error Response Format:
{
    "code": "ERROR_CODE",
    "message": "User-friendly error message",
    "details": "Technical details (optional)",
    "suggestions": ["Action 1", "Action 2"],
    "timestamp": "2026-03-27T12:20:00Z"
}
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# Initialize logger for error tracking
logger = logging.getLogger("memograph.api.errors")


# ============================================================================
# Error Code Definitions
# ============================================================================


class ErrorCode:
    """
    Centralized error code definitions for consistent error handling.

    Error codes follow a pattern: CATEGORY_SPECIFIC_ERROR
    - 4xx errors: Client errors (user's fault)
    - 5xx errors: Server errors (our fault)
    """

    # Resource Not Found (404)
    MEMORY_NOT_FOUND = "MEMORY_NOT_FOUND"
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    VAULT_NOT_FOUND = "VAULT_NOT_FOUND"

    # Validation Errors (400)
    INVALID_QUERY = "INVALID_QUERY"
    INVALID_MEMORY_ID = "INVALID_MEMORY_ID"
    INVALID_MEMORY_TYPE = "INVALID_MEMORY_TYPE"
    INVALID_TAGS = "INVALID_TAGS"
    INVALID_SALIENCE = "INVALID_SALIENCE"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_PAGINATION = "INVALID_PAGINATION"
    INVALID_SORT_FIELD = "INVALID_SORT_FIELD"

    # Operation Errors (422)
    MEMORY_ALREADY_EXISTS = "MEMORY_ALREADY_EXISTS"
    CIRCULAR_LINK_DETECTED = "CIRCULAR_LINK_DETECTED"
    MAX_DEPTH_EXCEEDED = "MAX_DEPTH_EXCEEDED"

    # Server Errors (500)
    DATABASE_ERROR = "DATABASE_ERROR"
    FILE_SYSTEM_ERROR = "FILE_SYSTEM_ERROR"
    GRAPH_ERROR = "GRAPH_ERROR"
    INDEXING_ERROR = "INDEXING_ERROR"

    # Timeout Errors (504)
    SEARCH_TIMEOUT = "SEARCH_TIMEOUT"
    OPERATION_TIMEOUT = "OPERATION_TIMEOUT"

    # Service Unavailable (503)
    KERNEL_NOT_INITIALIZED = "KERNEL_NOT_INITIALIZED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


# ============================================================================
# Structured Error Response
# ============================================================================


class MemoGraphError(Exception):
    """
    Base exception class for MemoGraph with structured error information.

    This exception includes:
    - Error code for programmatic handling
    - User-friendly message
    - Optional technical details
    - Actionable suggestions for resolution
    - HTTP status code

    Usage:
        raise MemoGraphError(
            code=ErrorCode.MEMORY_NOT_FOUND,
            message="Memory not found",
            details="No memory with ID '123' exists",
            suggestions=["Check the memory ID", "Try searching for the memory"],
            status_code=404
        )
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: str | None = None,
        suggestions: list[str] | None = None,
        status_code: int = 500,
        **extra,
    ):
        """
        Initialize a structured error.

        Args:
            code: Error code from ErrorCode class
            message: User-friendly error message
            details: Technical details for debugging (optional)
            suggestions: List of actionable suggestions (optional)
            status_code: HTTP status code (default: 500)
            **extra: Additional context to include in error response
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.suggestions = suggestions or []
        self.status_code = status_code
        self.extra = extra
        self.timestamp = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> dict[str, Any]:
        """
        Convert error to a dictionary for JSON response.

        Returns:
            Dictionary with error information
        """
        response = {
            "code": self.code,
            "message": self.message,
            "timestamp": self.timestamp,
        }

        # Only include details if present
        if self.details:
            response["details"] = self.details

        # Only include suggestions if present
        if self.suggestions:
            response["suggestions"] = self.suggestions

        # Include any extra context
        if self.extra:
            response.update(self.extra)

        return response


# ============================================================================
# Convenience Error Factories
# ============================================================================


def memory_not_found_error(memory_id: str) -> MemoGraphError:
    """
    Create a 'memory not found' error with helpful suggestions.

    Args:
        memory_id: The ID that was not found

    Returns:
        Configured MemoGraphError instance
    """
    return MemoGraphError(
        code=ErrorCode.MEMORY_NOT_FOUND,
        message=f"Memory '{memory_id}' not found",
        details=f"No memory with ID '{memory_id}' exists in the vault",
        suggestions=[
            "Check that the memory ID is correct",
            "The memory may have been deleted",
            "Try searching for the memory by title or content",
            "Use GET /api/memories to list all available memories",
        ],
        status_code=404,
        memory_id=memory_id,
    )


def invalid_query_error(query: str, reason: str) -> MemoGraphError:
    """
    Create an 'invalid query' error with helpful suggestions.

    Args:
        query: The invalid query string
        reason: Why the query is invalid

    Returns:
        Configured MemoGraphError instance
    """
    return MemoGraphError(
        code=ErrorCode.INVALID_QUERY,
        message="Search query is invalid",
        details=f"Query '{query}' is invalid: {reason}",
        suggestions=[
            "Ensure query is not empty",
            "Try a simpler query",
            "Remove special characters if present",
            "Check query syntax",
        ],
        status_code=400,
        query=query,
        reason=reason,
    )


def search_timeout_error(query: str, timeout_seconds: float) -> MemoGraphError:
    """
    Create a 'search timeout' error with helpful suggestions.

    Args:
        query: The query that timed out
        timeout_seconds: How long the search ran before timing out

    Returns:
        Configured MemoGraphError instance
    """
    return MemoGraphError(
        code=ErrorCode.SEARCH_TIMEOUT,
        message="Search operation timed out",
        details=f"Search for '{query}' exceeded {timeout_seconds}s timeout",
        suggestions=[
            "Try a more specific query",
            "Reduce search depth parameter",
            "Filter by tags to narrow results",
            "Use a higher min_salience value",
            "The vault may be very large - consider indexing optimization",
        ],
        status_code=504,
        query=query,
        timeout_seconds=timeout_seconds,
    )


def invalid_memory_type_error(memory_type: str) -> MemoGraphError:
    """
    Create an 'invalid memory type' error with valid options.

    Args:
        memory_type: The invalid memory type

    Returns:
        Configured MemoGraphError instance
    """
    # Import here to avoid circular dependency
    from ...core.enums import MemoryType

    valid_types: list[str] = [t.value for t in MemoryType]
    valid_types_str = ", ".join(valid_types)

    return MemoGraphError(
        code=ErrorCode.INVALID_MEMORY_TYPE,
        message=f"Invalid memory type: '{memory_type}'",
        details=f"Memory type must be one of: {valid_types_str}",
        suggestions=[
            f"Use one of the valid memory types: {valid_types_str}",
            "Check the MemoryType documentation",
            "Memory type is case-sensitive",
        ],
        status_code=400,
        memory_type=memory_type,
        valid_types=valid_types,
    )


def file_system_error(
    operation: str, path: str, original_error: Exception
) -> MemoGraphError:
    """
    Create a 'file system error' with helpful suggestions.

    Args:
        operation: The operation that failed (e.g., "read", "write", "delete")
        path: The file path involved
        original_error: The original exception

    Returns:
        Configured MemoGraphError instance
    """
    return MemoGraphError(
        code=ErrorCode.FILE_SYSTEM_ERROR,
        message=f"File system {operation} operation failed",
        details=f"Failed to {operation} '{path}': {str(original_error)}",
        suggestions=[
            "Check that the file path exists",
            "Verify you have necessary permissions",
            "Check available disk space",
            "Ensure the vault directory is accessible",
            "Check file system logs for more details",
        ],
        status_code=500,
        operation=operation,
        path=path,
        original_error=type(original_error).__name__,
    )


def kernel_not_initialized_error() -> MemoGraphError:
    """
    Create a 'kernel not initialized' error.

    Returns:
        Configured MemoGraphError instance
    """
    return MemoGraphError(
        code=ErrorCode.KERNEL_NOT_INITIALIZED,
        message="MemoGraph kernel is not initialized",
        details="The kernel instance is not available on the app state",
        suggestions=[
            "Ensure the FastAPI app was started correctly",
            "Check that startup event handlers ran successfully",
            "Verify vault path configuration",
            "Check server logs for initialization errors",
            "Restart the server",
        ],
        status_code=503,
    )


# ============================================================================
# FastAPI Error Handler
# ============================================================================


async def memograph_error_handler(
    request: Request, exc: MemoGraphError
) -> JSONResponse:
    """
    FastAPI error handler for MemoGraphError exceptions.

    This handler:
    1. Logs the error with full context
    2. Returns a structured JSON response
    3. Includes appropriate HTTP status code

    Args:
        request: The FastAPI request object
        exc: The MemoGraphError exception

    Returns:
        JSONResponse with structured error information

    Usage in FastAPI app:
        app.add_exception_handler(MemoGraphError, memograph_error_handler)
    """
    # Log the error with full context
    logger.error(
        f"API Error: {exc.code}",
        extra={
            "error_code": exc.code,
            "message": exc.message,
            "details": exc.details,
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method,
            **exc.extra,
        },
    )

    # Return structured JSON response
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all error handler for unexpected exceptions.

    This handler:
    1. Logs the full exception with traceback
    2. Returns a generic error message to clients
    3. Hides internal details for security

    Args:
        request: The FastAPI request object
        exc: Any unhandled exception

    Returns:
        JSONResponse with generic error message

    Usage in FastAPI app:
        app.add_exception_handler(Exception, generic_error_handler)
    """
    # Log the full exception with traceback
    logger.exception(
        "Unexpected API error",
        extra={
            "path": request.url.path,
            "method": request.method,
            "exception_type": type(exc).__name__,
        },
    )

    # Return generic error (don't expose internal details)
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "details": "Please check server logs for more information",
            "suggestions": [
                "Try the request again",
                "Check request parameters",
                "Contact support if the problem persists",
            ],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


# ============================================================================
# Validation Helpers
# ============================================================================


def validate_memory_id(memory_id: str) -> None:
    """
    Validate memory ID format.

    Memory IDs should be non-empty strings without special characters.

    Args:
        memory_id: The memory ID to validate

    Raises:
        MemoGraphError: If validation fails
    """
    if not memory_id:
        raise MemoGraphError(
            code=ErrorCode.INVALID_MEMORY_ID,
            message="Memory ID cannot be empty",
            suggestions=["Provide a valid memory ID"],
            status_code=400,
        )

    if not isinstance(memory_id, str):
        raise MemoGraphError(
            code=ErrorCode.INVALID_MEMORY_ID,
            message="Memory ID must be a string",
            details=f"Got type: {type(memory_id).__name__}",
            suggestions=["Ensure memory ID is a string"],
            status_code=400,
        )


def validate_pagination(page: int, page_size: int) -> None:
    """
    Validate pagination parameters.

    Args:
        page: Page number (must be >= 1)
        page_size: Items per page (must be 1-100)

    Raises:
        MemoGraphError: If validation fails
    """
    if page < 1:
        raise MemoGraphError(
            code=ErrorCode.INVALID_PAGINATION,
            message="Page number must be >= 1",
            details=f"Got page={page}",
            suggestions=["Use page=1 for the first page"],
            status_code=400,
            page=page,
        )

    if page_size < 1 or page_size > 100:
        raise MemoGraphError(
            code=ErrorCode.INVALID_PAGINATION,
            message="Page size must be between 1 and 100",
            details=f"Got page_size={page_size}",
            suggestions=["Use page_size between 1 and 100"],
            status_code=400,
            page_size=page_size,
        )


def validate_salience(salience: float) -> None:
    """
    Validate salience value.

    Salience must be between 0.0 and 1.0.

    Args:
        salience: The salience value to validate

    Raises:
        MemoGraphError: If validation fails
    """
    if not isinstance(salience, (int, float)):
        raise MemoGraphError(
            code=ErrorCode.INVALID_SALIENCE,
            message="Salience must be a number",
            details=f"Got type: {type(salience).__name__}",
            suggestions=["Provide a numeric salience value between 0.0 and 1.0"],
            status_code=400,
        )

    if salience < 0.0 or salience > 1.0:
        raise MemoGraphError(
            code=ErrorCode.INVALID_SALIENCE,
            message="Salience must be between 0.0 and 1.0",
            details=f"Got salience={salience}",
            suggestions=[
                "Use a value between 0.0 (lowest) and 1.0 (highest)",
                "0.5 is a typical default value",
            ],
            status_code=400,
            salience=salience,
        )


def validate_query(query: str) -> None:
    """
    Validate search query.

    Query must be a non-empty string.

    Args:
        query: The search query to validate

    Raises:
        MemoGraphError: If validation fails
    """
    if not query:
        raise invalid_query_error(query or "", "Query cannot be empty")

    if not isinstance(query, str):
        raise MemoGraphError(
            code=ErrorCode.INVALID_QUERY,
            message="Query must be a string",
            details=f"Got type: {type(query).__name__}",
            suggestions=["Provide a string query"],
            status_code=400,
        )

    if not query.strip():
        raise invalid_query_error(query, "Query cannot be whitespace only")
