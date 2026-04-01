"""
Search Endpoints for MemoGraph API

This module provides REST API endpoints for searching memories:
- POST /search - Hybrid retrieval search (keyword + semantic + graph)
- GET /search/autocomplete - Autocomplete suggestions for titles and tags

All endpoints use structured error handling with helpful error messages
and actionable suggestions for resolution.
"""

import logging
import time

from fastapi import APIRouter, Query, Request

from ..errors import (
    ErrorCode,
    MemoGraphError,
    invalid_query_error,
    kernel_not_initialized_error,
    search_timeout_error,
    validate_query,
    validate_salience,
)
from ..models import MemoryResponse, SearchRequest, SearchResponse

# Initialize logger for this module
logger = logging.getLogger("memograph.api.search")

# Create FastAPI router for search endpoints
router = APIRouter()

# Search timeout in seconds
SEARCH_TIMEOUT = 30.0


@router.post("/search", response_model=SearchResponse)
async def search_memories(search_req: SearchRequest, request: Request):
    """
    Search memories using hybrid retrieval (keyword + semantic + graph).

    This endpoint supports multiple search strategies:
    - keyword: BM25-style keyword matching
    - semantic: Embedding-based semantic search
    - hybrid: Combined keyword + semantic (default)
    - graph: Graph traversal based on wikilinks

    Args:
        search_req: Search request with query and filters
        request: FastAPI request object (injected)

    Returns:
        SearchResponse with matching memories and metadata

    Raises:
        MemoGraphError: If validation fails or search fails

    Example:
        POST /api/search
        {
            "query": "python tips",
            "tags": ["coding"],
            "top_k": 10,
            "depth": 2
        }
    """
    # Validate query
    try:
        validate_query(search_req.query)
    except MemoGraphError:
        raise

    # Get kernel instance from app state
    kernel = getattr(request.app.state, "kernel", None)
    if not kernel:
        raise kernel_not_initialized_error()

    start_time = time.time()

    try:
        logger.info(
            f"Search request: query='{search_req.query}', tags={search_req.tags}, top_k={search_req.top_k}"
        )

        # Build query
        query_builder = kernel.query().search(search_req.query)

        if search_req.tags:
            query_builder = query_builder.with_tags(search_req.tags)

        if search_req.min_salience > 0:
            # Validate salience value
            validate_salience(search_req.min_salience)
            query_builder = query_builder.min_salience(search_req.min_salience)

        query_builder = query_builder.depth(search_req.depth).limit(search_req.top_k)

        # Execute search with timeout check
        results = await query_builder.execute_async()

        execution_time = time.time() - start_time

        # Check if search exceeded timeout
        if execution_time > SEARCH_TIMEOUT:
            logger.warning(
                f"Search took {execution_time:.2f}s (exceeded {SEARCH_TIMEOUT}s timeout)"
            )
            raise search_timeout_error(search_req.query, SEARCH_TIMEOUT)

        logger.info(
            f"Search completed: found {len(results)} results in {execution_time * 1000:.2f}ms"
        )

        # Convert to response models
        memory_responses = [
            MemoryResponse(
                id=node.id,
                title=node.title,
                content=node.content,
                memory_type=node.memory_type.value,
                tags=node.tags,
                salience=node.salience,
                access_count=node.access_count,
                last_accessed=node.last_accessed.isoformat(),
                created_at=node.created_at.isoformat(),
                modified_at=node.modified_at.isoformat(),
                links=node.links,
                backlinks=node.backlinks,
                source_path=node.source_path,
            )
            for node in results
        ]

        execution_time_ms = execution_time * 1000

        return SearchResponse(
            query=search_req.query,
            results=memory_responses,
            total=len(memory_responses),
            execution_time_ms=round(execution_time_ms, 2),
        )

    except MemoGraphError:
        # Re-raise structured errors
        raise
    except TimeoutError as e:
        logger.error(f"Search timeout: {str(e)}")
        raise search_timeout_error(search_req.query, SEARCH_TIMEOUT)
    except Exception as e:
        logger.error(f"Search failed: {str(e)}", exc_info=True)
        raise MemoGraphError(
            code=ErrorCode.DATABASE_ERROR,
            message="Search operation failed",
            details=f"Failed to execute search: {str(e)}",
            suggestions=[
                "Try a simpler query",
                "Reduce the number of results (top_k parameter)",
                "Check that the vault is indexed correctly",
                "Verify vault health with GET /api/health",
                "Check server logs for detailed error information",
            ],
            status_code=500,
            query=search_req.query,
        )


@router.get("/search/autocomplete")
async def autocomplete(
    request: Request,
    q: str = Query(..., min_length=1, description="Query string for autocomplete"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of suggestions"),
):
    """
    Autocomplete suggestions based on memory titles and tags.

    Provides real-time suggestions as users type in the search box.
    Searches both memory titles and tags for matches.

    Args:
        q: Query string (minimum 1 character)
        limit: Maximum number of suggestions to return (1-50)
        request: FastAPI request object (injected)

    Returns:
        Dictionary with autocomplete suggestions

    Raises:
        MemoGraphError: If validation fails or autocomplete fails

    Example:
        GET /api/search/autocomplete?q=pyth&limit=10

        Response:
        {
            "suggestions": [
                {
                    "type": "memory",
                    "value": "Python Tips",
                    "id": "123",
                    "salience": 0.8
                },
                {
                    "type": "tag",
                    "value": "python"
                }
            ]
        }
    """
    # Validate query
    if not q or not q.strip():
        raise invalid_query_error(q, "Autocomplete query cannot be empty")

    # Get kernel instance from app state
    kernel = getattr(request.app.state, "kernel", None)
    if not kernel:
        raise kernel_not_initialized_error()

    try:
        logger.debug(f"Autocomplete request: q='{q}', limit={limit}")

        # Get all nodes
        all_nodes = kernel.graph.all_nodes()

        q_lower = q.lower()
        suggestions = []

        # Search in titles
        for node in all_nodes:
            if q_lower in node.title.lower():
                suggestions.append(
                    {
                        "type": "memory",
                        "value": node.title,
                        "id": node.id,
                        "salience": node.salience,
                    }
                )

        # Search in tags
        all_tags = set()
        for node in all_nodes:
            all_tags.update(node.tags)

        for tag in all_tags:
            if q_lower in tag.lower():
                suggestions.append({"type": "tag", "value": tag})

        # Sort by relevance and limit
        # Memories with higher salience come first, then tags
        suggestions.sort(
            key=lambda x: (
                x["type"] == "tag",  # Tags come after memories
                -x.get("salience", 0),  # Higher salience first
            )
        )

        limited_suggestions = suggestions[:limit]

        logger.debug(f"Autocomplete completed: {len(limited_suggestions)} suggestions")

        return {"suggestions": limited_suggestions}

    except MemoGraphError:
        # Re-raise structured errors
        raise
    except Exception as e:
        logger.error(f"Autocomplete failed: {str(e)}", exc_info=True)
        raise MemoGraphError(
            code=ErrorCode.DATABASE_ERROR,
            message="Autocomplete operation failed",
            details=f"Failed to generate suggestions: {str(e)}",
            suggestions=[
                "Try a different query",
                "Check that the vault is indexed",
                "Verify vault health with GET /api/health",
                "Check server logs for detailed error information",
            ],
            status_code=500,
            query=q,
        )
