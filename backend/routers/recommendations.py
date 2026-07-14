"""Model recommendation endpoints: which model fits which task.

Rankings are built from observed events - real reliability on the caller's
own workload, not benchmark scores. Models are ranked within each task type
by failure rate, then cost, then latency; models with fewer than
``min_events`` events are listed but never recommended.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, and_
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

from database import get_db
from models import FailureEvent, TaskTypeEnum
from schemas import (
    RecommendationsResponse,
    TaskRecommendation,
    TaskModelStats,
    TimePeriod,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _rank_key(stats: TaskModelStats):
    """Reliability first, then cost, then latency; unknown cost/latency last."""
    return (
        not stats.sample_sufficient,
        stats.failure_rate,
        stats.average_cost_usd if stats.average_cost_usd is not None else float("inf"),
        stats.average_latency_ms if stats.average_latency_ms is not None else float("inf"),
    )


@router.get(
    "/recommendations",
    response_model=RecommendationsResponse,
    summary="Rank models per task type by observed reliability and cost",
)
async def get_recommendations(
    task_type: Optional[TaskTypeEnum] = Query(None, description="Limit to one task type"),
    hours: int = Query(720, ge=1, le=8760, description="Look back N hours"),
    min_events: int = Query(20, ge=1, le=100000, description="Events required before a model can be recommended"),
    db: AsyncSession = Depends(get_db),
):
    """
    For each task type, rank models by observed failure rate (ties broken by
    cost per call, then latency) and pick a recommended model.

    Only events ingested with a ``task_type`` participate. A model with fewer
    than ``min_events`` events for a task is shown but marked
    ``sample_sufficient: false`` and never recommended.
    """
    try:
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)

        conditions = [
            FailureEvent.timestamp >= time_threshold,
            FailureEvent.task_type.isnot(None),
        ]
        if task_type is not None:
            conditions.append(FailureEvent.task_type == task_type.value)

        stmt = select(
            FailureEvent.task_type,
            FailureEvent.model_name,
            func.max(FailureEvent.provider).label("provider"),
            func.count().label("total_events"),
            func.count(
                case((FailureEvent.failure_type.isnot(None), 1))
            ).label("failure_count"),
            func.avg(FailureEvent.latency_ms).label("avg_latency"),
            func.avg(FailureEvent.cost_usd).label("avg_cost"),
        ).where(and_(*conditions)).group_by(
            FailureEvent.task_type, FailureEvent.model_name
        )
        rows = (await db.execute(stmt)).mappings().all()

        # Most common failure type per (task, model), failures only
        top_failure_stmt = select(
            FailureEvent.task_type,
            FailureEvent.model_name,
            FailureEvent.failure_type,
            func.count().label("cnt"),
        ).where(
            and_(*conditions, FailureEvent.failure_type.isnot(None))
        ).group_by(
            FailureEvent.task_type, FailureEvent.model_name, FailureEvent.failure_type
        )
        top_failure_rows = (await db.execute(top_failure_stmt)).mappings().all()

        top_failure: dict = {}
        for row in top_failure_rows:
            key = (row["task_type"], row["model_name"])
            if key not in top_failure or row["cnt"] > top_failure[key][1]:
                ftype = row["failure_type"]
                label = ftype.value if hasattr(ftype, "value") else str(ftype)
                top_failure[key] = (label, row["cnt"])

        # Group model stats by task
        by_task: dict = {}
        for row in rows:
            total = row["total_events"]
            failures = row["failure_count"]
            failure_rate = failures / total if total > 0 else 0.0
            key = (row["task_type"], row["model_name"])
            stats = TaskModelStats(
                model_name=row["model_name"],
                provider=row["provider"],
                total_events=total,
                failure_count=failures,
                failure_rate=round(failure_rate, 4),
                success_rate=round(1.0 - failure_rate, 4),
                average_latency_ms=row["avg_latency"],
                average_cost_usd=row["avg_cost"],
                top_failure_type=top_failure.get(key, (None,))[0],
                sample_sufficient=total >= min_events,
            )
            by_task.setdefault(row["task_type"], []).append(stats)

        tasks = []
        for task, model_stats in sorted(by_task.items()):
            ranked = sorted(model_stats, key=_rank_key)
            recommended = next((m.model_name for m in ranked if m.sample_sufficient), None)
            if recommended is None:
                caveat = (
                    f"No model has {min_events}+ events for this task yet; "
                    "rankings are indicative only."
                )
            elif any(not m.sample_sufficient for m in ranked):
                caveat = (
                    "Some models have too few events to rank confidently "
                    "and were excluded from the recommendation."
                )
            else:
                caveat = None

            tasks.append(
                TaskRecommendation(
                    task_type=task,
                    total_events=sum(m.total_events for m in ranked),
                    ranked_models=ranked,
                    recommended_model=recommended,
                    caveat=caveat,
                )
            )

        end_time = datetime.now(timezone.utc)
        return RecommendationsResponse(
            period=TimePeriod(start=end_time - timedelta(hours=hours), end=end_time, hours=hours),
            min_events=min_events,
            tasks=tasks,
        )

    except Exception as e:
        logger.error(f"Error computing recommendations: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute recommendations",
        )
