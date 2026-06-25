"""
Graph Endpoints for MemoGraph API

This module provides REST API endpoints for graph operations:
- GET /graph - Get graph data for visualization with filters
- GET /graph/neighbors/{node_id} - Get neighbors of a specific node

All endpoints use structured error handling with helpful error messages
and actionable suggestions for resolution.
"""

import logging

from fastapi import APIRouter, Depends, Query

from ....core.kernel import MemoryKernel
from ..errors import (
    ErrorCode,
    MemoGraphError,
    memory_not_found_error,
    validate_salience,
)
from ..models import GraphEdge, GraphNode, GraphResponse
from ..tenant_resolver import kernel_for_request

# Initialize logger for this module
logger = logging.getLogger("memograph.api.graph")

# Create FastAPI router for graph endpoints
router = APIRouter()


@router.get("/graph", response_model=GraphResponse)
async def get_graph_data(
    limit: int | None = Query(
        None, ge=1, le=500, description="Maximum number of nodes to return"
    ),
    min_salience: float = Query(
        0.0, ge=0.0, le=1.0, description="Minimum salience score"
    ),
    tags: str | None = Query(None, description="Comma-separated tags to filter by"),
    focus_node: str | None = Query(
        None, description="Center graph around this node ID"
    ),
    kernel: MemoryKernel = Depends(kernel_for_request),
):
    """
    Get graph data for visualization.

    Returns nodes and edges for the memory graph, optionally filtered
    and focused on a specific node. Useful for building interactive
    graph visualizations.

    Args:
        request: FastAPI request object (injected)
        limit: Maximum number of nodes to return (1-500)
        min_salience: Minimum salience score to include (0.0-1.0)
        tags: Comma-separated list of tags to filter by
        focus_node: Node ID to center the graph around (includes neighbors within depth 2)

    Returns:
        GraphResponse with nodes and edges

    Raises:
        MemoGraphError: If validation fails or graph operation fails

    Example:
        GET /api/graph?limit=100&min_salience=0.5&tags=python,coding&focus_node=123
    """
    try:
        logger.debug(
            f"Graph request: limit={limit}, min_salience={min_salience}, tags={tags}, focus_node={focus_node}"
        )

        # Get all nodes
        all_nodes = kernel.graph.all_nodes()
        logger.debug(f"Total nodes in graph: {len(all_nodes)}")

        # Apply filters
        filtered_nodes = all_nodes

        # Filter by minimum salience if specified
        if min_salience > 0:
            validate_salience(min_salience)
            filtered_nodes = [n for n in filtered_nodes if n.salience >= min_salience]
            logger.debug(
                f"After salience filter (>={min_salience}): {len(filtered_nodes)} nodes"
            )

        # Filter by tags if specified (OR operation - matches any tag)
        if tags:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            if tag_list:
                filtered_nodes = [
                    n for n in filtered_nodes if any(tag in n.tags for tag in tag_list)
                ]
                logger.debug(
                    f"After tags filter ({tag_list}): {len(filtered_nodes)} nodes"
                )

        # If focus_node is specified, get its neighborhood
        if focus_node:
            focus = kernel.graph.get(focus_node)
            if not focus:
                raise memory_not_found_error(focus_node)

            # Get neighbors within depth 2
            neighbors = kernel.graph.neighbors(focus_node, depth=2)
            neighbor_ids = {n.id for n in neighbors}
            neighbor_ids.add(focus_node)  # Include the focus node itself
            filtered_nodes = [n for n in filtered_nodes if n.id in neighbor_ids]
            logger.debug(
                f"After focus_node filter (node={focus_node}, depth=2): {len(filtered_nodes)} nodes"
            )

        # Apply limit if specified
        if limit:
            if limit < 1 or limit > 500:
                raise MemoGraphError(
                    code=ErrorCode.INVALID_PAGINATION,
                    message="Graph limit must be between 1 and 500",
                    details=f"Got limit={limit}",
                    suggestions=[
                        "Use a limit between 1 and 500",
                        "Consider adding filters (tags, min_salience) to reduce results",
                        "Use focus_node to view a specific subgraph",
                    ],
                    status_code=400,
                    limit=limit,
                )

            # Sort by salience and take top N
            filtered_nodes.sort(key=lambda n: n.salience, reverse=True)
            filtered_nodes = filtered_nodes[:limit]
            logger.debug(f"After limit: {len(filtered_nodes)} nodes")

        # Build node list
        node_ids = {n.id for n in filtered_nodes}
        nodes = [
            GraphNode(
                id=node.id,
                title=node.title,
                memory_type=node.memory_type.value,
                salience=node.salience,
                tags=node.tags,
                link_count=len(node.links),
                backlink_count=len(node.backlinks),
            )
            for node in filtered_nodes
        ]

        # Build edge list (only edges between visible nodes)
        edges = []
        seen_edges = set()

        for node in filtered_nodes:
            for link in node.links:
                if link in node_ids:
                    edge_key = (node.id, link)
                    if edge_key not in seen_edges:
                        edges.append(
                            GraphEdge(source=node.id, target=link, type="wikilink")
                        )
                        seen_edges.add(edge_key)

        logger.info(f"Graph response: {len(nodes)} nodes, {len(edges)} edges")

        return GraphResponse(
            nodes=nodes, edges=edges, total_nodes=len(nodes), total_edges=len(edges)
        )

    except MemoGraphError:
        # Re-raise structured errors
        raise
    except Exception as e:
        logger.error(f"Graph operation failed: {str(e)}", exc_info=True)
        raise MemoGraphError(
            code=ErrorCode.GRAPH_ERROR,
            message="Failed to retrieve graph data",
            details=f"Graph operation failed: {str(e)}",
            suggestions=[
                "Check that the vault is indexed correctly",
                "Verify vault health with GET /api/health",
                "Try reducing the limit or adding filters",
                "Check server logs for detailed error information",
            ],
            status_code=500,
        )


@router.get("/graph/neighbors/{node_id}")
async def get_neighbors(
    node_id: str,
    depth: int = Query(1, ge=1, le=3, description="Depth of neighbor traversal (1-3)"),
    kernel: MemoryKernel = Depends(kernel_for_request),
):
    """
    Get neighbors of a specific node.

    Returns all nodes that are connected to the specified node
    within the given depth. Useful for exploring local subgraphs
    around a specific memory.

    Args:
        node_id: ID of the node to get neighbors for
        request: FastAPI request object (injected)
        depth: How many hops away to search (1-3)

    Returns:
        Dictionary with node information and its neighbors

    Raises:
        MemoGraphError: If node not found or operation fails

    Example:
        GET /api/graph/neighbors/123?depth=2

        Response:
        {
            "node_id": "123",
            "depth": 2,
            "neighbors": [...],
            "total": 15
        }
    """
    try:
        logger.debug(f"Neighbors request: node_id={node_id}, depth={depth}")

        # Check if node exists
        node = kernel.graph.get(node_id)
        if not node:
            raise memory_not_found_error(node_id)

        # Validate depth parameter
        if depth < 1 or depth > 3:
            raise MemoGraphError(
                code=ErrorCode.MAX_DEPTH_EXCEEDED,
                message="Depth must be between 1 and 3",
                details=f"Got depth={depth}",
                suggestions=[
                    "Use depth between 1 and 3",
                    "Depth 1 returns direct neighbors",
                    "Depth 2 returns neighbors of neighbors",
                    "Higher depths may return many nodes",
                ],
                status_code=400,
                depth=depth,
            )

        # Get neighbors at specified depth
        neighbors = kernel.graph.neighbors(node_id, depth=depth)

        logger.info(
            f"Found {len(neighbors)} neighbors for node {node_id} at depth {depth}"
        )

        return {
            "node_id": node_id,
            "depth": depth,
            "neighbors": [
                {
                    "id": n.id,
                    "title": n.title,
                    "memory_type": n.memory_type.value,
                    "salience": n.salience,
                    "tags": n.tags,
                    "link_count": len(n.links),
                    "backlink_count": len(n.backlinks),
                }
                for n in neighbors
            ],
            "total": len(neighbors),
        }

    except MemoGraphError:
        # Re-raise structured errors
        raise
    except Exception as e:
        logger.error(f"Get neighbors failed: {str(e)}", exc_info=True)
        raise MemoGraphError(
            code=ErrorCode.GRAPH_ERROR,
            message="Failed to get node neighbors",
            details=f"Neighbor retrieval failed for node '{node_id}': {str(e)}",
            suggestions=[
                "Check that the node ID is correct",
                "Try a smaller depth value",
                "Verify vault health with GET /api/health",
                "Check server logs for detailed error information",
            ],
            status_code=500,
            node_id=node_id,
            depth=depth,
        )
