"""Pattern detection and analysis endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta, timezone
import json
import logging

from database import get_db
from models import Pattern, FailureEvent
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
            Pattern.remediation_tested.is_(True)
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


@router.get(
    "/patterns/{pattern_id}/export",
    summary="Export a pattern's failing events as a JSONL eval set",
    response_class=Response,
)
async def export_pattern_events(
    pattern_id: str,
    limit: int = Query(500, ge=1, le=5000, description="Max events to export"),
    hours: int = Query(720, ge=1, le=8760, description="Look back N hours"),
    db: AsyncSession = Depends(get_db),
):
    """
    Download the prompts that hit this pattern as JSON Lines - one failing
    event per line - ready to use as a regression eval set when trying a
    fix or a different model.

    Events are matched by the pattern's (failure_type, model_name) signature,
    newest first.
    """
    try:
        pattern = (await db.execute(
            select(Pattern).where(Pattern.pattern_id == pattern_id)
        )).scalar_one_or_none()

        if not pattern:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pattern {pattern_id} not found",
            )

        time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        conditions = [
            FailureEvent.failure_type == pattern.failure_type,
            FailureEvent.timestamp >= time_threshold,
        ]
        if pattern.model_name:
            conditions.append(FailureEvent.model_name == pattern.model_name)

        events = (await db.execute(
            select(FailureEvent)
            .where(and_(*conditions))
            .order_by(FailureEvent.timestamp.desc())
            .limit(limit)
        )).scalars().all()

        lines = []
        for e in events:
            failure_type = e.failure_type.value if hasattr(e.failure_type, "value") else str(e.failure_type)
            severity = e.failure_severity.value if hasattr(e.failure_severity, "value") else e.failure_severity
            lines.append(json.dumps({
                "event_id": e.event_id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "model_name": e.model_name,
                "provider": e.provider,
                "task_type": e.task_type,
                "prompt": e.prompt,
                "response": e.response,
                "failure_type": failure_type,
                "failure_severity": severity,
                "confidence_score": e.confidence_score,
                "retrieval_score": e.retrieval_score,
                "latency_ms": e.latency_ms,
            }, ensure_ascii=False))

        return Response(
            content="\n".join(lines) + ("\n" if lines else ""),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="{pattern_id}.jsonl"',
                "X-Event-Count": str(len(lines)),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting pattern events: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export pattern events",
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
