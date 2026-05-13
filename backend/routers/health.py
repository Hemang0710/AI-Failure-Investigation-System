"""Health check endpoint."""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timezone
import logging

from schemas import HealthResponse
from database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request, db: AsyncSession = Depends(get_db)):
    """Check API health status with actual database connectivity."""
    db_status = "healthy"
    overall_status = "healthy"

    try:
        # Test database connectivity
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning(f"Database health check failed: {str(e)}")
        db_status = "unhealthy"
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now(timezone.utc),
        components={
            "api": "healthy",
            "database": db_status,
            "event_queue": "healthy",
            "analysis_engine": "healthy",
        },
    )
