"""System statistics endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta, timezone
import logging

from database import get_db
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
    try:
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)

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
            Pattern.remediation_tested.is_(True)
        )
        patterns_with_remediation = await db.scalar(remediation_query) or 0

        # Calculate failure rate trend by comparing first half vs second half
        half_hours = hours // 2
        mid_time = time_threshold + timedelta(hours=half_hours)

        # First half failure count
        first_half_query = select(func.count()).select_from(FailureEvent).where(
            and_(
                FailureEvent.timestamp >= time_threshold,
                FailureEvent.timestamp < mid_time,
                FailureEvent.failure_type.isnot(None),
            )
        )
        first_half_failures = await db.scalar(first_half_query) or 0

        # First half total count
        first_half_total_query = select(func.count()).select_from(FailureEvent).where(
            and_(
                FailureEvent.timestamp >= time_threshold,
                FailureEvent.timestamp < mid_time,
            )
        )
        first_half_total = await db.scalar(first_half_total_query) or 1

        # Second half failure count
        second_half_query = select(func.count()).select_from(FailureEvent).where(
            and_(
                FailureEvent.timestamp >= mid_time,
                FailureEvent.failure_type.isnot(None),
            )
        )
        second_half_failures = await db.scalar(second_half_query) or 0

        # Second half total count
        second_half_total_query = select(func.count()).select_from(FailureEvent).where(
            FailureEvent.timestamp >= mid_time
        )
        second_half_total = await db.scalar(second_half_total_query) or 1

        # Calculate failure rates for each half
        first_half_rate = first_half_failures / first_half_total if first_half_total > 0 else 0.0
        second_half_rate = second_half_failures / second_half_total if second_half_total > 0 else 0.0

        # Determine trend (>10% change threshold)
        if first_half_rate == 0:
            trend = "stable" if second_half_rate == 0 else "increasing"
        elif second_half_rate > first_half_rate * 1.1:
            trend = "increasing"
        elif second_half_rate < first_half_rate * 0.9:
            trend = "decreasing"
        else:
            trend = "stable"

        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        end_time = datetime.now(timezone.utc)

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
