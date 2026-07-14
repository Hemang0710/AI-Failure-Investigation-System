"""Failure query and detail endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from datetime import datetime, timedelta, timezone
import logging

from database import get_db
from models import FailureEvent
from schemas import FailuresQueryResponse, FailureEventResponse, FailureDetailResponse, PaginationInfo

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/failures",
    response_model=FailuresQueryResponse,
    summary="Query failure events",
)
async def get_failures(
    type: str = Query(None, description="Failure type filter"),
    model: str = Query(None, description="Model name filter"),
    hours: int = Query(24, ge=1, le=720, description="Look back N hours"),
    severity: str = Query(None, description="Severity filter"),
    environment: str = Query(None, description="Environment filter"),
    session_id: str = Query(None, description="Session ID filter"),
    user_id: str = Query(None, description="User ID filter"),
    search: str = Query(None, description="Search prompt/response"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    sort: str = Query("-timestamp", description="Sort field"),
    db: AsyncSession = Depends(get_db),
):
    """
    Query failure events with filtering, pagination, and sorting.

    Supported filters:
    - type: failure type (hallucination, empty_response, etc)
    - model: model name
    - severity: critical, high, medium, low
    - environment: production, staging, dev
    - session_id: session ID
    - user_id: user ID
    - search: full-text search in prompt/response
    - hours: look back N hours (default 24, max 720)

    Sort options: timestamp, confidence_score, latency_ms
    """
    try:
        # Build filters. Success events (failure_type IS NULL) live in the
        # same table but are not failures, so they are always excluded here.
        filters = []
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        filters.append(FailureEvent.timestamp >= time_threshold)
        filters.append(FailureEvent.failure_type.isnot(None))

        if type:
            filters.append(FailureEvent.failure_type == type)
        if model:
            filters.append(FailureEvent.model_name == model)
        if severity:
            filters.append(FailureEvent.failure_severity == severity)
        if environment:
            filters.append(FailureEvent.environment == environment)
        if session_id:
            filters.append(FailureEvent.session_id == session_id)
        if user_id:
            filters.append(FailureEvent.user_id == user_id)
        if search:
            filters.append(
                or_(
                    FailureEvent.prompt.ilike(f"%{search}%"),
                    FailureEvent.response.ilike(f"%{search}%"),
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(FailureEvent)
        if filters:
            count_query = count_query.where(and_(*filters))
        total_count = await db.scalar(count_query)

        # Get paginated results
        query = select(FailureEvent)
        if filters:
            query = query.where(and_(*filters))

        # Sort
        if sort.startswith("-"):
            field_name = sort[1:]
            query = query.order_by(getattr(FailureEvent, field_name).desc())
        else:
            query = query.order_by(getattr(FailureEvent, sort).asc())

        # Pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        results = await db.execute(query)
        events = results.scalars().all()

        total_pages = (total_count + limit - 1) // limit

        return FailuresQueryResponse(
            failures=[FailureEventResponse.model_validate(e) for e in events],
            pagination=PaginationInfo(
                total_count=total_count,
                page=page,
                limit=limit,
                total_pages=total_pages,
            ),
            filters_applied={
                "type": type,
                "model": model,
                "hours": hours,
                "severity": severity,
            },
        )

    except Exception as e:
        logger.error(f"Error querying failures: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query failures",
        )


@router.get(
    "/failures/{event_id}",
    response_model=FailureDetailResponse,
    summary="Get failure details",
)
async def get_failure_detail(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve detailed information about a specific failure event.

    Includes all metadata, retrieval results, quality metrics, and feedback.
    """
    try:
        query = select(FailureEvent).where(FailureEvent.event_id == event_id)
        result = await db.execute(query)
        event = result.scalar_one_or_none()

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event {event_id} not found",
            )

        return FailureDetailResponse.model_validate(event)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving failure detail: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve failure details",
        )
