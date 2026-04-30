"""System statistics endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
import logging

from database import get_db
from auth import verify_api_key
from models import FailureEvent, Pattern
from schemas import SystemStats, TimePeriod

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/stats",
    response_model=SystemStats,
    summary="Get system statistics",
)
async def get_system_stats(
    hours: int = Query(24, ge=1, le=720, description="Look back N hours"),
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregate statistics across all failures.

    Shows overall system health metrics:
    - Total events and failure count
    - Failure rate
    - Failure type distribution
    - Severity distribution
    - Model with highest failures
    - Active patterns
    """
    # Verify API key
    token = await verify_api_key(authorization)

    try:
        time_threshold = datetime.utcnow() - timedelta(hours=hours)

        # Total events
        total_events_query = select(func.count()).select_from(FailureEvent).where(
            FailureEvent.timestamp >= time_threshold
        )
        total_events = await db.scalar(total_events_query) or 0

        # Total failures (events with failure_type set)
        total_failures_query = select(func.count()).select_from(FailureEvent).where(
            and_(
                FailureEvent.failure_type.isnot(None),
                FailureEvent.timestamp >= time_threshold,
            )
        )
        total_failures = await db.scalar(total_failures_query) or 0

        # Failure rate
        failure_rate = total_failures / total_events if total_events > 0 else 0.0

        # Failure type distribution
        failure_type_query = select(
            FailureEvent.failure_type, func.count()
        ).select_from(FailureEvent).where(
            FailureEvent.timestamp >= time_threshold
        ).group_by(FailureEvent.failure_type)
        failure_type_result = await db.execute(failure_type_query)
        failure_type_rows = failure_type_result.all()

        failure_type_dist = {}
        for ftype, count in failure_type_rows:
            if ftype:
                failure_type_dist[str(ftype)] = count

        # Severity distribution
        severity_query = select(
            FailureEvent.failure_severity, func.count()
        ).select_from(FailureEvent).where(
            FailureEvent.timestamp >= time_threshold
        ).group_by(FailureEvent.failure_severity)
        severity_result = await db.execute(severity_query)
        severity_rows = severity_result.all()

        severity_dist = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        }
        for severity, count in severity_rows:
            if severity:
                severity_dist[severity] = count

        # Average confidence when failing
        avg_confidence_query = select(func.avg(FailureEvent.confidence_score)).select_from(
            FailureEvent
        ).where(
            and_(
                FailureEvent.failure_type.isnot(None),
                FailureEvent.timestamp >= time_threshold,
            )
        )
        avg_confidence = await db.scalar(avg_confidence_query)

        # Model with highest failures
        model_failure_query = select(
            FailureEvent.model_name, func.count()
        ).select_from(FailureEvent).where(
            FailureEvent.timestamp >= time_threshold
        ).group_by(FailureEvent.model_name).order_by(func.count().desc()).limit(1)
        model_failure_result = await db.execute(model_failure_query)
        model_row = model_failure_result.first()
        top_model = model_row[0] if model_row else None

        # Active patterns
        active_patterns_query = select(func.count()).select_from(Pattern)
        active_patterns = await db.scalar(active_patterns_query) or 0

        # Patterns with remediation
        remediation_query = select(func.count()).select_from(Pattern).where(
            Pattern.remediation_tested == True
        )
        patterns_with_remediation = await db.scalar(remediation_query) or 0

        # Determine trend (would need historical data for proper implementation)
        # For MVP, default to "stable"
        trend = "stable"

        start_time = datetime.utcnow() - timedelta(hours=hours)
        end_time = datetime.utcnow()

        return SystemStats(
            time_period=TimePeriod(
                hours=hours,
                start=start_time,
                end=end_time,
            ),
            total_events=total_events,
            total_failures=total_failures,
            overall_failure_rate=round(failure_rate, 4),
            failure_type_distribution=failure_type_dist,
            severity_distribution=severity_dist,
            average_confidence_when_fails=avg_confidence,
            model_with_highest_failures=top_model,
            failure_rate_trend=trend,
            active_patterns=active_patterns,
            patterns_with_remediation=patterns_with_remediation,
        )

    except Exception as e:
        logger.error(f"Error querying system stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query system statistics",
        )
