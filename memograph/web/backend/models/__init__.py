"""Pydantic models for request/response validation."""

from typing import Any

from pydantic import BaseModel, Field, validator


class MemoryResponse(BaseModel):
    """Response model for a single memory."""

    id: str
    title: str
    content: str
    memory_type: str
    tags: list[str] = []
    salience: float
    access_count: int
    last_accessed: str
    created_at: str
    modified_at: str
    links: list[str] = []
    backlinks: list[str] = []
    source_path: str | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "id": "python-tips",
                "title": "Python Tips",
                "content": "Use list comprehensions for better performance",
                "memory_type": "fact",
                "tags": ["python", "programming"],
                "salience": 0.8,
                "access_count": 5,
                "last_accessed": "2026-03-22T18:00:00Z",
                "created_at": "2026-03-20T10:00:00Z",
                "modified_at": "2026-03-22T15:00:00Z",
                "links": ["performance-optimization"],
                "backlinks": ["python-best-practices"],
            }
        }


class MemoryListResponse(BaseModel):
    """Response model for memory list."""

    memories: list[MemoryResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class CreateMemoryRequest(BaseModel):
    """Request model for creating a new memory."""

    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    memory_type: str = Field(
        default="fact", pattern="^(episodic|semantic|procedural|fact)$"
    )
    tags: list[str] = Field(default_factory=list)
    salience: float = Field(default=0.5, ge=0.0, le=1.0)
    meta: dict[str, Any] | None = None

    @validator("tags")
    def validate_tags(cls, v):
        return [tag.strip().lstrip("#") for tag in v if tag.strip()]


class UpdateMemoryRequest(BaseModel):
    """Request model for updating a memory."""

    content: str | None = None
    tags: list[str] | None = None
    salience: float | None = Field(None, ge=0.0, le=1.0)
    meta: dict[str, Any] | None = None


class SearchRequest(BaseModel):
    """Request model for search."""

    query: str = Field(..., min_length=1)
    tags: list[str] | None = None
    memory_type: str | None = None
    min_salience: float = Field(default=0.0, ge=0.0, le=1.0)
    depth: int = Field(default=2, ge=0, le=5)
    top_k: int = Field(default=10, ge=1, le=100)
    strategy: str = Field(default="hybrid", pattern="^(keyword|semantic|hybrid|graph)$")
    boost_recent: bool = False


class SearchResponse(BaseModel):
    """Response model for search results."""

    query: str
    results: list[MemoryResponse]
    total: int
    execution_time_ms: float


class GraphNode(BaseModel):
    """Graph node representation."""

    id: str
    title: str
    memory_type: str
    salience: float
    tags: list[str]
    link_count: int
    backlink_count: int


class GraphEdge(BaseModel):
    """Graph edge representation."""

    source: str
    target: str
    type: str = "wikilink"


class GraphResponse(BaseModel):
    """Response model for graph data."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_nodes: int
    total_edges: int


class AnalyticsResponse(BaseModel):
    """Response model for analytics."""

    total_memories: int
    memory_type_distribution: dict[str, int]
    tag_distribution: dict[str, int]
    avg_salience: float
    total_links: int
    most_connected_nodes: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]
    salience_distribution: dict[str, int]


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    vault_path: str
    total_memories: int
    total_entities: int
    gam_enabled: bool
    timestamp: str


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str
    detail: str | None = None
    code: str | None = None
