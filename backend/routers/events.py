"""Event ingestion endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert
from datetime import datetime, timezone
import uuid
import logging
import asyncio

from database import get_db, AsyncSessionLocal
from auth import verify_api_key
from models import FailureEvent, APIKey
from schemas import BatchEventIngestion, EventIngestionResponse
from services.pattern_engine import run_pattern_analysis

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/events",
    response_model=EventIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest failure events",
)
async def ingest_events(
    batch: BatchEventIngestion,
    request: Request,
    api_key: APIKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept batch failure event submissions from SDKs or integrations.

    - **events**: List of failure events (max 1000 per batch)
    - Returns: batch_id for tracking

    For now, events are processed synchronously. In production,
    would queue for async processing.
    """
    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    request_id = getattr(request.state, "request_id", None)

    try:
        events_to_insert = []

        for event_data in batch.events:
            event_id = f"evt_{uuid.uuid4().hex[:8]}"

            event = FailureEvent(
                event_id=event_id,
                user_id=api_key.user_id,
                timestamp=event_data.timestamp,
                model_name=event_data.model_name,
                provider=event_data.provider,
                prompt=event_data.prompt,
                response=event_data.response,
                response_length=event_data.response_length,
                latency_ms=event_data.latency_ms,
                confidence_score=event_data.confidence_score,
                failure_type=event_data.failure_type,
                failure_severity=event_data.failure_severity,
                retrieval_score=event_data.retrieval_score,
                retrieval_results=event_data.retrieval_results,
                context_relevance=event_data.context_relevance,
                environment=event_data.environment or "production",
                session_id=event_data.session_id,
                tags=event_data.tags,
                event_metadata=event_data.event_metadata or {},
            )
            events_to_insert.append(event)

        # Bulk insert
        await db.execute(
            insert(FailureEvent),
            [
                {
                    "event_id": e.event_id,
                    "user_id": e.user_id,
                    "timestamp": e.timestamp,
                    "model_name": e.model_name,
                    "provider": e.provider,
                    "prompt": e.prompt,
                    "response": e.response,
                    "response_length": e.response_length,
                    "latency_ms": e.latency_ms,
                    "confidence_score": e.confidence_score,
                    "failure_type": e.failure_type,
                    "failure_severity": e.failure_severity,
                    "retrieval_score": e.retrieval_score,
                    "retrieval_results": e.retrieval_results,
                    "context_relevance": e.context_relevance,
                    "environment": e.environment,
                    "session_id": e.session_id,
                    "tags": e.tags,
                    "event_metadata": e.event_metadata,
                }
                for e in events_to_insert
            ],
        )

        await db.commit()

        logger.info(
            f"Ingested {len(batch.events)} events",
            extra={
                "batch_id": batch_id,
                "request_id": request_id,
                "event_count": len(batch.events),
            },
        )

        # Trigger pattern analysis asynchronously
        async def _trigger_analysis():
            async with AsyncSessionLocal() as analysis_db:
                await run_pattern_analysis(db=analysis_db, hours=168, min_occurrences=3)

        asyncio.create_task(_trigger_analysis())

        return EventIngestionResponse(
            status="received",
            event_count=len(batch.events),
            batch_id=batch_id,
            timestamp=datetime.now(timezone.utc),
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error ingesting events: {str(e)}",
            extra={"batch_id": batch_id, "request_id": request_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to ingest events",
        )


@router.post(
    "/events/trigger-analysis",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Manually trigger pattern analysis",
    tags=["events"],
)
async def trigger_pattern_analysis(
    hours: int = Query(168, ge=1, le=720, description="Analyze events from last N hours"),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger pattern analysis on existing failure events.
    Useful for ad-hoc analysis or dashboard-initiated re-analysis.
    Returns 202 Accepted - analysis runs in background.
    """
    async def _trigger():
        async with AsyncSessionLocal() as analysis_db:
            result = await run_pattern_analysis(db=analysis_db, hours=hours, min_occurrences=3)
            logger.info(f"Manual pattern analysis triggered: {result} patterns")

    asyncio.create_task(_trigger())

    return {
        "status": "analysis_triggered",
        "hours": hours,
        "timestamp": datetime.now(timezone.utc),
    }
