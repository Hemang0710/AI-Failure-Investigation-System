"""Health check endpoint."""

from fastapi import APIRouter, Request
from datetime import datetime
from schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """Check API health status."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        components={
            "api": "healthy",
            "database": "healthy",  # TODO: actual database check
            "event_queue": "healthy",
            "analysis_engine": "healthy",
        },
    )
