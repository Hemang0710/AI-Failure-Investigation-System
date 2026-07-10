"""Model performance endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from datetime import datetime, timedelta, timezone
import logging

from database import get_db
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
    try:
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Single GROUP BY query to get all stats per model
        stmt = select(
            FailureEvent.model_name,
            func.count().label("total_events"),
            func.count(
                case((FailureEvent.failure_type.isnot(None), 1))
            ).label("failure_count"),
            func.avg(FailureEvent.confidence_score).label("avg_confidence"),
            func.avg(FailureEvent.latency_ms).label("avg_latency"),
            func.count(func.distinct(FailureEvent.failure_type)).label("distinct_types"),
            func.sum(
                case((FailureEvent.failure_severity == "critical", 1), else_=0)
            ).label("sev_critical"),
            func.sum(
                case((FailureEvent.failure_severity == "high", 1), else_=0)
            ).label("sev_high"),
            func.sum(
                case((FailureEvent.failure_severity == "medium", 1), else_=0)
            ).label("sev_medium"),
            func.sum(
                case((FailureEvent.failure_severity == "low", 1), else_=0)
            ).label("sev_low"),
        ).where(
            FailureEvent.timestamp >= time_threshold
        ).group_by(FailureEvent.model_name)

        result = await db.execute(stmt)
        rows = result.mappings().all()

        stats_list = []
        for row in rows:
            total = row["total_events"]
            failures = row["failure_count"]
            failure_rate = failures / total if total > 0 else 0.0

            severity_breakdown = {
                "critical": row["sev_critical"] or 0,
                "high": row["sev_high"] or 0,
                "medium": row["sev_medium"] or 0,
                "low": row["sev_low"] or 0,
            }

            stats_list.append(
                ModelStats(
                    model_name=row["model_name"],
                    total_events=total,
                    failure_count=failures,
                    failure_rate=round(failure_rate, 4),
                    average_confidence=row["avg_confidence"],
                    average_latency_ms=row["avg_latency"],
                    distinct_failure_types=row["distinct_types"] or 0,
                    severity_breakdown=severity_breakdown,
                )
            )

        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        end_time = datetime.now(timezone.utc)

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
