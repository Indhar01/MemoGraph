"""Analytics endpoints for MemoGraph API."""

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ....core.kernel import MemoryKernel
from ..models import AnalyticsResponse
from ..tenant_resolver import kernel_for_request

router = APIRouter()


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(kernel: MemoryKernel = Depends(kernel_for_request)):
    """Get analytics and statistics about the memory vault."""

    try:
        all_nodes = kernel.graph.all_nodes()
        total_memories = len(all_nodes)

        if total_memories == 0:
            return AnalyticsResponse(
                total_memories=0,
                memory_type_distribution={},
                tag_distribution={},
                avg_salience=0.0,
                total_links=0,
                most_connected_nodes=[],
                recent_activity=[],
                salience_distribution={},
            )

        # Memory type distribution
        memory_type_dist = Counter(n.memory_type.value for n in all_nodes)

        # Tag distribution (top 20)
        all_tags = []
        for node in all_nodes:
            all_tags.extend(node.tags)
        tag_dist = dict(Counter(all_tags).most_common(20))

        # Average salience
        avg_salience = sum(n.salience for n in all_nodes) / total_memories

        # Total links
        total_links = sum(len(n.links) for n in all_nodes)

        # Most connected nodes
        nodes_with_connections: list[dict[str, Any]] = [
            {
                "id": n.id,
                "title": n.title,
                "connections": len(n.links) + len(n.backlinks),
                "salience": n.salience,
            }
            for n in all_nodes
        ]
        nodes_with_connections.sort(key=lambda x: int(x["connections"]), reverse=True)
        most_connected = nodes_with_connections[:10]

        # Recent activity
        recent_nodes = sorted(all_nodes, key=lambda n: n.modified_at, reverse=True)[:10]
        recent_activity = [
            {
                "id": n.id,
                "title": n.title,
                "memory_type": n.memory_type.value,
                "modified_at": n.modified_at.isoformat(),
                "salience": n.salience,
            }
            for n in recent_nodes
        ]

        # Salience distribution
        salience_buckets = {
            "0.0-0.2": 0,
            "0.2-0.4": 0,
            "0.4-0.6": 0,
            "0.6-0.8": 0,
            "0.8-1.0": 0,
        }

        for node in all_nodes:
            if node.salience < 0.2:
                salience_buckets["0.0-0.2"] += 1
            elif node.salience < 0.4:
                salience_buckets["0.2-0.4"] += 1
            elif node.salience < 0.6:
                salience_buckets["0.4-0.6"] += 1
            elif node.salience < 0.8:
                salience_buckets["0.6-0.8"] += 1
            else:
                salience_buckets["0.8-1.0"] += 1

        return AnalyticsResponse(
            total_memories=total_memories,
            memory_type_distribution=dict(memory_type_dist),
            tag_distribution=tag_dist,
            avg_salience=round(avg_salience, 3),
            total_links=total_links,
            most_connected_nodes=most_connected,
            recent_activity=recent_activity,
            salience_distribution=salience_buckets,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate analytics: {str(e)}"
        )
