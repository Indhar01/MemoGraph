"""
Memory Management Endpoints for MemoGraph API

This module provides REST API endpoints for CRUD operations on memories:
- GET /memories - List all memories with pagination and filtering
- GET /memories/{memory_id} - Get a specific memory by ID
- POST /memories - Create a new memory
- PUT /memories/{memory_id} - Update an existing memory
- DELETE /memories/{memory_id} - Delete a memory

All endpoints use structured error handling with helpful error messages
and actionable suggestions for resolution.
"""

from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional
import logging

from ..models import (
    MemoryResponse,
    MemoryListResponse,
    CreateMemoryRequest,
    UpdateMemoryRequest
)
from ....core.enums import MemoryType
from ..errors import (
    MemoGraphError,
    ErrorCode,
    memory_not_found_error,
    invalid_memory_type_error,
    file_system_error,
    kernel_not_initialized_error,
    validate_memory_id,
    validate_pagination,
    validate_salience,
)

# Initialize logger for this module
logger = logging.getLogger("memograph.api.memories")

# Create FastAPI router for memory endpoints
router = APIRouter()


@router.get("/memories", response_model=MemoryListResponse)
async def list_memories(
    request: Request,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    memory_type: Optional[str] = Query(None, description="Filter by memory type"),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    min_salience: float = Query(0.0, ge=0.0, le=1.0, description="Minimum salience score"),
    sort_by: str = Query("modified_at", pattern="^(salience|created_at|modified_at|title)$", description="Field to sort by"),
    order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order (asc or desc)")
):
    """
    List memories with pagination and filtering.

    This endpoint provides a paginated list of all memories in the vault with
    optional filtering by memory type, tags, and salience score. Results can
    be sorted by various fields.

    Args:
        request: FastAPI request object (injected)
        page: Page number to retrieve (starts at 1)
        page_size: Number of items per page (1-100)
        memory_type: Optional filter by memory type (e.g., "episodic", "semantic")
        tags: Optional comma-separated list of tags to filter by
        min_salience: Minimum salience score to include (0.0-1.0)
        sort_by: Field to sort by (salience, created_at, modified_at, title)
        order: Sort order (asc or desc)

    Returns:
        MemoryListResponse with paginated results and metadata

    Raises:
        MemoGraphError: If validation fails or kernel is not initialized

    Example:
        GET /api/memories?page=1&page_size=20&memory_type=episodic&tags=python,coding
    """
    # Validate pagination parameters
    try:
        validate_pagination(page, page_size)
    except MemoGraphError:
        raise

    # Get kernel instance from app state
    kernel = getattr(request.app.state, 'kernel', None)
    if not kernel:
        raise kernel_not_initialized_error()

    try:
        logger.debug(f"Listing memories: page={page}, page_size={page_size}, memory_type={memory_type}")
        # Get all nodes from the memory graph
        all_nodes = kernel.graph.all_nodes()
        logger.debug(f"Found {len(all_nodes)} total memories in vault")

        # Apply filters sequentially
        filtered_nodes = all_nodes

        # Filter by memory type if specified
        if memory_type:
            # Validate that the memory type is valid
            try:
                from ....core.enums import MemoryType
                # This will raise ValueError if invalid
                MemoryType(memory_type)
            except ValueError:
                raise invalid_memory_type_error(memory_type)

            filtered_nodes = [n for n in filtered_nodes if n.memory_type.value == memory_type]
            logger.debug(f"After memory_type filter: {len(filtered_nodes)} memories")

        # Filter by tags if specified (OR operation - matches any tag)
        if tags:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            if tag_list:
                filtered_nodes = [
                    n for n in filtered_nodes
                    if any(tag in n.tags for tag in tag_list)
                ]
                logger.debug(f"After tags filter ({tag_list}): {len(filtered_nodes)} memories")

        # Filter by minimum salience if specified
        if min_salience > 0:
            validate_salience(min_salience)
            filtered_nodes = [n for n in filtered_nodes if n.salience >= min_salience]
            logger.debug(f"After salience filter (>={min_salience}): {len(filtered_nodes)} memories")

        # Sort the filtered results
        reverse = (order == "desc")
        logger.debug(f"Sorting by {sort_by} ({order})")

        if sort_by == "salience":
            filtered_nodes.sort(key=lambda n: n.salience, reverse=reverse)
        elif sort_by == "created_at":
            filtered_nodes.sort(key=lambda n: n.created_at, reverse=reverse)
        elif sort_by == "modified_at":
            filtered_nodes.sort(key=lambda n: n.modified_at, reverse=reverse)
        elif sort_by == "title":
            # Case-insensitive title sorting
            filtered_nodes.sort(key=lambda n: n.title.lower(), reverse=reverse)

        # Apply pagination to the filtered and sorted results
        total = len(filtered_nodes)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_nodes = filtered_nodes[start_idx:end_idx]

        logger.debug(f"Returning page {page}: items {start_idx}-{end_idx} of {total}")

        # Convert memory nodes to API response models
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
                source_path=node.source_path
            )
            for node in page_nodes
        ]

        # Return paginated response with metadata
        return MemoryListResponse(
            memories=memory_responses,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(end_idx < total)


@router.get("/memories/{memory_id}", response_model=MemoryResponse)
async def get_memory(memory_id: str, request: Request):
    """Get a specific memory by ID."""
    kernel = request.app.state.kernel

    try:
        node = kernel.graph.get(memory_id)
        if not node:
            raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")

        return MemoryResponse(
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
            source_path=node.source_path
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get memory: {str(e)}")


@router.post("/memories", response_model=dict)
async def create_memory(memory: CreateMemoryRequest, request: Request):
    """Create a new memory."""
    kernel = request.app.state.kernel

    try:
        # Convert memory_type string to enum
        memory_type_enum = MemoryType(memory.memory_type)

        # Create memory
        file_path = await kernel.remember_async(
            title=memory.title,
            content=memory.content,
            memory_type=memory_type_enum,
            tags=memory.tags,
            salience=memory.salience,
            meta=memory.meta
        )

        # Re-ingest to update graph
        await kernel.ingest_async(force=False)

        # Extract memory ID from file path
        from pathlib import Path
        memory_id = Path(file_path).stem

        return {
            "id": memory_id,
            "file_path": file_path,
            "message": "Memory created successfully"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create memory: {str(e)}")


@router.put("/memories/{memory_id}", response_model=dict)
async def update_memory(memory_id: str, update: UpdateMemoryRequest, request: Request):
    """Update an existing memory."""
    kernel = request.app.state.kernel

    try:
        # Check if memory exists
        node = kernel.graph.get(memory_id)
        if not node:
            raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")

        # Prepare update data
        update_data = {}
        if update.content:
            update_data["content"] = update.content
        if update.tags:
            update_data["tags"] = update.tags
        if update.salience is not None:
            update_data["salience"] = update.salience
        if update.meta:
            update_data["meta"] = update.meta

        # Update memory
        updated, errors = await kernel.update_many_async(
            [(memory_id, update_data)],
            continue_on_error=False
        )

        if errors:
            raise HTTPException(status_code=500, detail=f"Update failed: {errors[0][1]}")

        # Re-ingest
        await kernel.ingest_async(force=False)

        return {
            "id": memory_id,
            "message": "Memory updated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update memory: {str(e)}")


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, request: Request):
    """Delete a memory."""
    kernel = request.app.state.kernel

    try:
        node = kernel.graph.get(memory_id)
        if not node:
            raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")

        # Delete the file
        if node.source_path:
            from pathlib import Path
            file_path = Path(node.source_path)
            if file_path.exists():
                file_path.unlink()

        # Remove from graph
        kernel.graph.remove_node(memory_id)

        return {
            "id": memory_id,
            "message": "Memory deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete memory: {str(e)}")
