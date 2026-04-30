"""Model performance endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
import logging

from database import get_db
from auth import verify_api_key
from models import FailureEvent
from schemas import ModelsQueryResponse, ModelStats, TimePeriod

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/models",
    response_model=ModelsQueryResponse,
    summary="Get model performance summary",
)
async def get_model_stats(
    hours: int = Query(24, ge=1, le=720, description="Look back N hours"),
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Get statistics and failure rates per model.

    Shows:
    - Total events processed
    - Failure count and rate
    - Average confidence and latency
    - Failure type distribution
    - Severity breakdown
    """
    # Verify API key
    token = await verify_api_key(authorization)

    try:
        time_threshold = datetime.utcnow() - timedelta(hours=hours)

        # Get all unique models
        models_query = select(FailureEvent.model_name).where(
            FailureEvent.timestamp >= time_threshold
        ).distinct()
        result = await db.execute(models_query)
        model_names = result.scalars().all()

        stats_list = []

        for model_name in model_names:
            # Count total events
            total_query = select(func.count()).select_from(FailureEvent).where(
                and_(
                    FailureEvent.model_name == model_name,
                    FailureEvent.timestamp >= time_threshold,
                )
            )
            total_count = await db.scalar(total_query) or 0

            # Count failures
            failure_query = select(func.count()).select_from(FailureEvent).where(
                and_(
                    FailureEvent.model_name == model_name,
                    FailureEvent.failure_type.isnot(None),
                    FailureEvent.timestamp >= time_threshold,
                )
            )
            failure_count = await db.scalar(failure_query) or 0

            # Calculate metrics
            avg_confidence_query = select(func.avg(FailureEvent.confidence_score)).select_from(
                FailureEvent
            ).where(
                and_(
                    FailureEvent.model_name == model_name,
                    FailureEvent.timestamp >= time_threshold,
                )
            )
            avg_confidence = await db.scalar(avg_confidence_query)

            avg_latency_query = select(func.avg(FailureEvent.latency_ms)).select_from(
                FailureEvent
            ).where(
                and_(
                    FailureEvent.model_name == model_name,
                    FailureEvent.timestamp >= time_threshold,
                )
            )
            avg_latency = await db.scalar(avg_latency_query)

            # Failure types
            failure_types_query = select(
                FailureEvent.failure_type, func.count()
            ).select_from(FailureEvent).where(
                and_(
                    FailureEvent.model_name == model_name,
                    FailureEvent.timestamp >= time_threshold,
                )
            ).group_by(FailureEvent.failure_type)
            failure_types_result = await db.execute(failure_types_query)
            distinct_types = len(failure_types_result.all())

            # Severity breakdown
            severity_query = select(
                FailureEvent.failure_severity, func.count()
            ).select_from(FailureEvent).where(
                and_(
                    FailureEvent.model_name == model_name,
                    FailureEvent.timestamp >= time_threshold,
                )
            ).group_by(FailureEvent.failure_severity)
            severity_result = await db.execute(severity_query)
            severity_rows = severity_result.all()

            severity_breakdown = {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
            }
            for severity, count in severity_rows:
                if severity:
                    severity_breakdown[severity] = count

            failure_rate = failure_count / total_count if total_count > 0 else 0.0

            stats_list.append(
                ModelStats(
                    model_name=model_name,
                    total_events=total_count,
                    failure_count=failure_count,
                    failure_rate=round(failure_rate, 4),
                    average_confidence=avg_confidence,
                    average_latency_ms=avg_latency,
                    distinct_failure_types=distinct_types,
                    severity_breakdown=severity_breakdown,
                )
            )

        start_time = datetime.utcnow() - timedelta(hours=hours)
        end_time = datetime.utcnow()

        return ModelsQueryResponse(
            models=stats_list,
            period=TimePeriod(
                start=start_time,
                end=end_time,
                hours=hours,
            ),
        )

    except Exception as e:
        logger.error(f"Error querying model stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query model statistics",
        )
