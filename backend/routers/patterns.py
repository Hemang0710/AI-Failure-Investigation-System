"""Pattern detection and analysis endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone
import logging

from database import get_db
from models import Pattern
from schemas import PatternsQueryResponse, PatternResponse, PatternsSummary, PatternFeedbackCreate, PatternFeedbackResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/patterns",
    response_model=PatternsQueryResponse,
    summary="Get failure patterns",
)
async def get_patterns(
    model: str = Query(None, description="Filter by model name"),
    type: str = Query(None, description="Filter by failure type"),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    sort: str = Query("-occurrence_count", description="Sort field"),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve recurring failure patterns with aggregated statistics.

    Patterns represent systematic issues that affect multiple requests.
    Each pattern shows:
    - Occurrence count
    - Affected users
    - Average metrics (confidence, latency, retrieval score)
    - Suggested remediation
    - Severity breakdown

    Sort options: occurrence_count, last_seen, severity
    """
    try:
        query = select(Pattern)

        # Apply filters
        if model:
            query = query.where(Pattern.model_name == model)
        if type:
            query = query.where(Pattern.failure_type == type)

        # Sort
        if sort.startswith("-"):
            field_name = sort[1:]
            query = query.order_by(getattr(Pattern, field_name).desc())
        else:
            query = query.order_by(getattr(Pattern, sort).asc())

        query = query.limit(limit)

        result = await db.execute(query)
        patterns = result.scalars().all()

        # Calculate summary stats
        total_patterns_query = select(func.count()).select_from(Pattern)
        total_patterns = await db.scalar(total_patterns_query)

        patterns_with_remediation_query = select(func.count()).select_from(Pattern).where(
            Pattern.remediation_tested == True
        )
        patterns_with_remediation = await db.scalar(patterns_with_remediation_query)

        avg_occurrences_query = select(func.avg(Pattern.occurrence_count)).select_from(Pattern)
        avg_occurrences = await db.scalar(avg_occurrences_query) or 0.0

        return PatternsQueryResponse(
            patterns=[PatternResponse.model_validate(p) for p in patterns],
            summary=PatternsSummary(
                total_patterns=total_patterns or 0,
                patterns_with_remediation=patterns_with_remediation or 0,
                avg_occurrences_per_pattern=float(avg_occurrences),
            ),
        )

    except Exception as e:
        logger.error(f"Error querying patterns: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query patterns",
        )


@router.post(
    "/patterns/{pattern_id}/feedback",
    response_model=PatternFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit pattern remediation feedback",
)
async def submit_pattern_feedback(
    pattern_id: str,
    feedback: PatternFeedbackCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Record whether a suggested remediation was tested and effective.

    Used to track which pattern fixes actually work in production.
    """
    try:
        # Find pattern
        query = select(Pattern).where(Pattern.pattern_id == pattern_id)
        result = await db.execute(query)
        pattern = result.scalar_one_or_none()

        if not pattern:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pattern {pattern_id} not found",
            )

        # Update pattern with feedback
        pattern.remediation_tested = feedback.remediation_tested
        pattern.remediation_effectiveness = feedback.remediation_effectiveness
        pattern.updated_at = datetime.now(timezone.utc)

        db.add(pattern)
        await db.commit()
        await db.refresh(pattern)

        logger.info(f"Pattern feedback recorded for {pattern_id}")

        return PatternFeedbackResponse(
            feedback_id=f"fb_{pattern_id}",
            pattern_id=pattern_id,
            timestamp=datetime.now(timezone.utc),
            status="recorded",
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error recording pattern feedback: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record pattern feedback",
        )
