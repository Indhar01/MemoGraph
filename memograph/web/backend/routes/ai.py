"""
AI Features Endpoints for MemoGraph API

This module provides REST API endpoints for AI-powered features:
- POST /ai/suggest-tags - Get tag suggestions for content
- POST /ai/suggest-links - Get link suggestions for content
- GET /ai/detect-gaps - Detect knowledge gaps in vault
- GET /ai/analyze-kb - Comprehensive knowledge base analysis
- POST /ai/feedback - Record user feedback on suggestions

All endpoints use structured error handling with helpful error messages
and actionable suggestions for resolution.
"""

import logging
import time

from fastapi import APIRouter, Depends, Query

from ....core.kernel import MemoryKernel
from ..errors import (
    ErrorCode,
    MemoGraphError,
)
from ..models import (
    FeedbackRequest,
    GapDetectionResponse,
    KnowledgeBaseAnalysisResponse,
    KnowledgeGapItem,
    LinkSuggestionItem,
    LinkSuggestionRequest,
    LinkSuggestionResponse,
    TagSuggestionItem,
    TagSuggestionRequest,
    TagSuggestionResponse,
)
from ..tenant_resolver import kernel_for_request

# Initialize logger for this module
logger = logging.getLogger("memograph.api.ai")

# Create FastAPI router for AI endpoints
router = APIRouter()


@router.post("/ai/suggest-tags", response_model=TagSuggestionResponse)
async def suggest_tags(
    tag_req: TagSuggestionRequest,
    kernel: MemoryKernel = Depends(kernel_for_request),
):
    """
    Suggest tags for content using AI analysis.

    This endpoint analyzes content and suggests relevant tags based on:
    - Keyword frequency analysis
    - Semantic similarity with existing tags
    - Content structure analysis
    - Related notes analysis

    Args:
        tag_req: Tag suggestion request with content and parameters
        request: FastAPI request object (injected)

    Returns:
        TagSuggestionResponse with suggested tags and confidence scores

    Raises:
        MemoGraphError: If validation fails or suggestion generation fails

    Example:
        POST /api/ai/suggest-tags
        {
            "content": "Python tips for better performance...",
            "title": "Python Tips",
            "existing_tags": ["python"],
            "min_confidence": 0.3,
            "max_suggestions": 5
        }
    """

    start_time = time.time()

    try:
        logger.info(
            f"Tag suggestion request: title='{tag_req.title}', "
            f"content_len={len(tag_req.content)}, existing_tags={tag_req.existing_tags}"
        )

        # Import here to avoid circular dependencies
        from ....ai.auto_tagger import AutoTagger

        # Initialize AutoTagger with request parameters
        tagger = AutoTagger(
            kernel,
            min_confidence=tag_req.min_confidence,
            max_suggestions=tag_req.max_suggestions,
        )

        # Get tag suggestions
        suggestions = await tagger.suggest_tags(
            content=tag_req.content,
            title=tag_req.title,
            existing_tags=tag_req.existing_tags,
        )

        execution_time = time.time() - start_time

        logger.info(
            f"Tag suggestions generated: {len(suggestions)} tags in {execution_time * 1000:.2f}ms"
        )

        # Convert to response models
        suggestion_items = [
            TagSuggestionItem(
                tag=s.tag,
                confidence=round(s.confidence, 3),
                reason=s.reason,
                source=s.source,
            )
            for s in suggestions
        ]

        return TagSuggestionResponse(
            suggestions=suggestion_items,
            total=len(suggestion_items),
        )

    except MemoGraphError:
        # Re-raise structured errors
        raise
    except Exception as e:
        logger.error(f"Tag suggestion failed: {str(e)}", exc_info=True)
        raise MemoGraphError(
            code=ErrorCode.DATABASE_ERROR,
            message="Tag suggestion operation failed",
            details=f"Failed to generate tag suggestions: {str(e)}",
            suggestions=[
                "Ensure content is not empty",
                "Check that the vault is indexed correctly",
                "Verify embeddings are available for semantic analysis",
                "Check server logs for detailed error information",
            ],
            status_code=500,
        )


@router.post("/ai/suggest-links", response_model=LinkSuggestionResponse)
async def suggest_links(
    link_req: LinkSuggestionRequest,
    kernel: MemoryKernel = Depends(kernel_for_request),
):
    """
    Suggest wikilinks for content using AI analysis.

    This endpoint analyzes content and suggests relevant wikilinks based on:
    - Semantic similarity with other notes
    - Keyword matching with note titles
    - Graph neighborhood analysis
    - Bidirectional link opportunities

    Args:
        link_req: Link suggestion request with content and parameters
        request: FastAPI request object (injected)

    Returns:
        LinkSuggestionResponse with suggested links and confidence scores

    Raises:
        MemoGraphError: If validation fails or suggestion generation fails

    Example:
        POST /api/ai/suggest-links
        {
            "content": "Python tips for better performance...",
            "title": "Python Tips",
            "note_id": "python-tips",
            "existing_links": ["python-basics"],
            "min_confidence": 0.4,
            "max_suggestions": 10
        }
    """

    start_time = time.time()

    try:
        logger.info(
            f"Link suggestion request: title='{link_req.title}', "
            f"content_len={len(link_req.content)}, note_id={link_req.note_id}"
        )

        # Import here to avoid circular dependencies
        from ....ai.link_suggester import LinkSuggester

        # Initialize LinkSuggester with request parameters
        suggester = LinkSuggester(
            kernel,
            min_confidence=link_req.min_confidence,
            max_suggestions=link_req.max_suggestions,
        )

        # Get link suggestions
        suggestions = await suggester.suggest_links(
            content=link_req.content,
            title=link_req.title,
            note_id=link_req.note_id,
            existing_links=link_req.existing_links,
        )

        execution_time = time.time() - start_time

        logger.info(
            f"Link suggestions generated: {len(suggestions)} links in {execution_time * 1000:.2f}ms"
        )

        # Convert to response models
        suggestion_items = [
            LinkSuggestionItem(
                target_title=s.target_title,
                target_id=s.target_id,
                confidence=round(s.confidence, 3),
                reason=s.reason,
                source=s.source,
                bidirectional=s.bidirectional,
            )
            for s in suggestions
        ]

        return LinkSuggestionResponse(
            suggestions=suggestion_items,
            total=len(suggestion_items),
        )

    except MemoGraphError:
        # Re-raise structured errors
        raise
    except Exception as e:
        logger.error(f"Link suggestion failed: {str(e)}", exc_info=True)
        raise MemoGraphError(
            code=ErrorCode.DATABASE_ERROR,
            message="Link suggestion operation failed",
            details=f"Failed to generate link suggestions: {str(e)}",
            suggestions=[
                "Ensure content is not empty",
                "Check that the vault is indexed correctly",
                "Verify embeddings are available for semantic analysis",
                "Ensure note_id exists if provided",
                "Check server logs for detailed error information",
            ],
            status_code=500,
        )


@router.get("/ai/detect-gaps", response_model=GapDetectionResponse)
async def detect_gaps(
    min_severity: float = Query(
        0.3, ge=0.0, le=1.0, description="Minimum severity threshold (0.0-1.0)"
    ),
    max_gaps: int = Query(
        20, ge=1, le=100, description="Maximum number of gaps to return"
    ),
    kernel: MemoryKernel = Depends(kernel_for_request),
):
    """
    Detect knowledge gaps in the vault.

    This endpoint analyzes the entire knowledge base to identify:
    - Missing topics (frequently mentioned but not documented)
    - Weak coverage (notes with shallow content)
    - Isolated notes (notes with few connections)
    - Missing links (mentions without wikilinks)

    Args:
        min_severity: Minimum severity threshold for gaps (0.0-1.0)
        max_gaps: Maximum number of gaps to return (1-100)
        request: FastAPI request object (injected)

    Returns:
        GapDetectionResponse with detected gaps sorted by severity

    Raises:
        MemoGraphError: If validation fails or gap detection fails

    Example:
        GET /api/ai/detect-gaps?min_severity=0.3&max_gaps=20

        Response:
        {
            "gaps": [
                {
                    "gap_type": "missing_topic",
                    "title": "Missing note about 'python'",
                    "description": "Term appears 15x across 8 notes but no dedicated note exists",
                    "severity": 0.8,
                    "suggestions": ["Create a note titled 'Python'"],
                    "related_notes": ["python-tips", "python-basics"]
                }
            ],
            "total": 10,
            "gap_types": {"missing_topic": 5, "weak_coverage": 3, "isolated_note": 2},
            "avg_severity": 0.65
        }
    """

    start_time = time.time()

    try:
        logger.info(
            f"Gap detection request: min_severity={min_severity}, max_gaps={max_gaps}"
        )

        # Import here to avoid circular dependencies
        from ....ai.gap_detector import GapDetector

        # Initialize GapDetector with request parameters
        detector = GapDetector(
            kernel,
            min_severity=min_severity,
            max_gaps=max_gaps,
        )

        # Detect gaps
        gaps = await detector.detect_gaps()

        execution_time = time.time() - start_time

        logger.info(
            f"Gap detection completed: {len(gaps)} gaps found in {execution_time * 1000:.2f}ms"
        )

        # Convert to response models
        gap_items = [
            KnowledgeGapItem(
                gap_type=g.gap_type,
                title=g.title,
                description=g.description,
                severity=round(g.severity, 2),
                suggestions=g.suggestions,
                related_notes=g.related_notes[:5],  # Limit related notes
            )
            for g in gaps
        ]

        # Calculate statistics
        from collections import Counter

        gap_types = dict(Counter(g.gap_type for g in gaps))
        avg_severity = sum(g.severity for g in gaps) / len(gaps) if gaps else 0.0

        return GapDetectionResponse(
            gaps=gap_items,
            total=len(gap_items),
            gap_types=gap_types,
            avg_severity=round(avg_severity, 2),
        )

    except MemoGraphError:
        # Re-raise structured errors
        raise
    except Exception as e:
        logger.error(f"Gap detection failed: {str(e)}", exc_info=True)
        raise MemoGraphError(
            code=ErrorCode.DATABASE_ERROR,
            message="Gap detection operation failed",
            details=f"Failed to detect knowledge gaps: {str(e)}",
            suggestions=[
                "Ensure the vault has enough notes for analysis (minimum 5)",
                "Check that the vault is indexed correctly",
                "Verify vault health with GET /api/health",
                "Check server logs for detailed error information",
            ],
            status_code=500,
        )


@router.get("/ai/analyze-kb", response_model=KnowledgeBaseAnalysisResponse)
async def analyze_knowledge_base(
    kernel: MemoryKernel = Depends(kernel_for_request),
):
    """
    Perform comprehensive knowledge base analysis.

    This endpoint provides a complete analysis of the knowledge base including:
    - Knowledge gaps (missing topics, weak coverage, etc.)
    - Topic clusters (groups of related notes)
    - Learning paths (suggested sequences for learning topics)
    - Overall knowledge base statistics

    Args:
        request: FastAPI request object (injected)

    Returns:
        KnowledgeBaseAnalysisResponse with comprehensive analysis

    Raises:
        MemoGraphError: If validation fails or analysis fails

    Example:
        GET /api/ai/analyze-kb

        Response:
        {
            "summary": {
                "total_gaps": 15,
                "gap_types": {"missing_topic": 8, "weak_coverage": 5, "isolated_note": 2},
                "avg_severity": 0.55,
                "total_clusters": 5,
                "total_paths": 3
            },
            "gaps": [...],
            "clusters": [...],
            "learning_paths": [...]
        }
    """

    start_time = time.time()

    try:
        logger.info("Knowledge base analysis request")

        # Import here to avoid circular dependencies
        from ....ai.gap_detector import GapDetector

        # Initialize GapDetector
        detector = GapDetector(kernel)

        # Perform comprehensive analysis
        analysis = await detector.analyze_knowledge_base()

        execution_time = time.time() - start_time

        logger.info(
            f"Knowledge base analysis completed in {execution_time * 1000:.2f}ms: "
            f"{analysis['summary']['total_gaps']} gaps, "
            f"{analysis['summary']['total_clusters']} clusters, "
            f"{analysis['summary']['total_paths']} paths"
        )

        return KnowledgeBaseAnalysisResponse(
            summary=analysis["summary"],
            gaps=analysis["gaps"],
            clusters=analysis["clusters"],
            learning_paths=analysis["learning_paths"],
        )

    except MemoGraphError:
        # Re-raise structured errors
        raise
    except Exception as e:
        logger.error(f"Knowledge base analysis failed: {str(e)}", exc_info=True)
        raise MemoGraphError(
            code=ErrorCode.DATABASE_ERROR,
            message="Knowledge base analysis operation failed",
            details=f"Failed to analyze knowledge base: {str(e)}",
            suggestions=[
                "Ensure the vault has enough notes for analysis",
                "Check that the vault is indexed correctly",
                "Verify vault health with GET /api/health",
                "Check server logs for detailed error information",
            ],
            status_code=500,
        )


@router.post("/ai/feedback")
async def record_feedback(
    feedback_req: FeedbackRequest,
    kernel: MemoryKernel = Depends(kernel_for_request),
):
    """
    Record user feedback on AI suggestions.

    This endpoint records whether a user accepted or rejected an AI suggestion,
    which helps improve future suggestions through learning.

    Supported feedback types:
    - tag: Feedback on tag suggestions
    - link: Feedback on link suggestions
    - gap: Feedback on knowledge gap suggestions

    Args:
        feedback_req: Feedback request with type, item ID, and accepted status
        request: FastAPI request object (injected)

    Returns:
        Success message

    Raises:
        MemoGraphError: If validation fails or feedback recording fails

    Example:
        POST /api/ai/feedback
        {
            "feedback_type": "tag",
            "item_id": "python",
            "accepted": true
        }
    """

    try:
        logger.info(
            f"Feedback request: type={feedback_req.feedback_type}, "
            f"item={feedback_req.item_id}, accepted={feedback_req.accepted}"
        )

        # Import AI classes
        from ....ai.auto_tagger import AutoTagger
        from ....ai.gap_detector import GapDetector
        from ....ai.link_suggester import LinkSuggester

        # Record feedback based on type
        if feedback_req.feedback_type == "tag":
            tagger = AutoTagger(kernel)
            tagger.record_feedback(feedback_req.item_id, feedback_req.accepted)
            logger.info(f"Tag feedback recorded for '{feedback_req.item_id}'")

        elif feedback_req.feedback_type == "link":
            suggester = LinkSuggester(kernel)
            suggester.record_feedback(feedback_req.item_id, feedback_req.accepted)
            logger.info(f"Link feedback recorded for '{feedback_req.item_id}'")

        elif feedback_req.feedback_type == "gap":
            detector = GapDetector(kernel)
            detector.record_gap_feedback(feedback_req.item_id, feedback_req.accepted)
            logger.info(f"Gap feedback recorded for '{feedback_req.item_id}'")

        else:
            raise MemoGraphError(
                code=ErrorCode.INVALID_QUERY,
                message=f"Invalid feedback type: {feedback_req.feedback_type}",
                details="Feedback type must be 'tag', 'link', or 'gap'",
                suggestions=[
                    "Use 'tag' for tag suggestions",
                    "Use 'link' for link suggestions",
                    "Use 'gap' for knowledge gap suggestions",
                ],
                status_code=400,
            )

        return {
            "success": True,
            "message": f"Feedback recorded for {feedback_req.feedback_type} suggestion",
            "item_id": feedback_req.item_id,
            "accepted": feedback_req.accepted,
        }

    except MemoGraphError:
        # Re-raise structured errors
        raise
    except Exception as e:
        logger.error(f"Feedback recording failed: {str(e)}", exc_info=True)
        raise MemoGraphError(
            code=ErrorCode.DATABASE_ERROR,
            message="Feedback recording operation failed",
            details=f"Failed to record feedback: {str(e)}",
            suggestions=[
                "Check that the feedback type is valid",
                "Ensure the item ID is correct",
                "Check server logs for detailed error information",
            ],
            status_code=500,
        )
