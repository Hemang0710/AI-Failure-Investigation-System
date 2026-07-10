"""Correlation analysis endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
import pandas as pd
import logging
import uuid

from database import get_db
from models import FailureEvent
from schemas import CorrelationsResponse, CorrelationItem

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/correlations",
    response_model=CorrelationsResponse,
    summary="Get failure factor correlations",
)
async def get_correlations(
    model: str = Query(None, description="Optional filter by model name"),
    hours: int = Query(168, ge=1, le=720, description="Look back N hours"),
    limit: int = Query(20, ge=1, le=50, description="Max number of correlations to return"),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze statistical correlations between operational factors and failure types.
    Uses phi coefficient to measure association strength.

    Returns strongest correlations found (absolute phi value > 0.1).
    """
    try:
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Load events into DataFrame
        stmt = select(
            FailureEvent.id,
            FailureEvent.model_name,
            FailureEvent.failure_type,
            FailureEvent.failure_severity,
            FailureEvent.confidence_score,
            FailureEvent.latency_ms,
            FailureEvent.retrieval_score,
            FailureEvent.timestamp,
        ).where(FailureEvent.timestamp >= time_threshold)

        if model:
            stmt = stmt.where(FailureEvent.model_name == model)

        result = await db.execute(stmt)
        rows = result.mappings().all()

        if not rows:
            return CorrelationsResponse(
                correlations=[],
                computed_at=datetime.now(timezone.utc),
                events_analyzed=0,
            )

        df = pd.DataFrame([dict(r) for r in rows])
        events_analyzed = len(df)

        # Skip correlation analysis if too few events
        if events_analyzed < 30:
            return CorrelationsResponse(
                correlations=[],
                computed_at=datetime.now(timezone.utc),
                events_analyzed=events_analyzed,
            )

        # Compute correlations
        correlations = _compute_correlations(df)

        # Sort by strength descending, limit results
        correlations = sorted(
            correlations,
            key=lambda x: x["correlation_strength"],
            reverse=True,
        )[:limit]

        # Build response
        correlation_items = [
            CorrelationItem(
                correlation_id=c["correlation_id"],
                factor_a=c["factor_a"],
                factor_b=c["factor_b"],
                correlation_strength=c["correlation_strength"],
                chi_squared=c.get("chi_squared"),
                p_value=c.get("p_value"),
                is_significant=abs(c["correlation_strength"]) > 0.3,
                interpretation=c["interpretation"],
            )
            for c in correlations
        ]

        return CorrelationsResponse(
            correlations=correlation_items,
            computed_at=datetime.now(timezone.utc),
            events_analyzed=events_analyzed,
        )

    except Exception as e:
        logger.error(f"Error analyzing correlations: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to analyze correlations",
        )


def _compute_correlations(df: pd.DataFrame) -> list:
    """
    Compute correlation signals from failure events.
    Returns list of correlation dicts with phi coefficients.
    """
    correlations = []

    # 1. Low retrieval score vs hallucination
    if "retrieval_score" in df.columns and not df["retrieval_score"].isna().all():
        low_retrieval = df["retrieval_score"] < 0.5
        is_hallucination = df["failure_type"] == "hallucination"

        phi = _compute_phi(low_retrieval, is_hallucination)
        if abs(phi) > 0.1:
            correlations.append({
                "correlation_id": f"corr_{uuid.uuid4().hex[:8]}",
                "factor_a": "low_retrieval_score (< 0.5)",
                "factor_b": "hallucination_failures",
                "correlation_strength": abs(phi),
                "interpretation": _interpret_correlation(phi, "low_retrieval_score", "hallucination_failures"),
            })

    # 2. High latency vs timeout
    if "latency_ms" in df.columns and not df["latency_ms"].isna().all():
        latency_p75 = df["latency_ms"].quantile(0.75)
        high_latency = df["latency_ms"] > latency_p75
        is_timeout = df["failure_type"] == "timeout"

        phi = _compute_phi(high_latency, is_timeout)
        if abs(phi) > 0.1:
            correlations.append({
                "correlation_id": f"corr_{uuid.uuid4().hex[:8]}",
                "factor_a": f"high_latency (> {latency_p75:.0f}ms)",
                "factor_b": "timeout_failures",
                "correlation_strength": abs(phi),
                "interpretation": _interpret_correlation(phi, "high_latency", "timeout_failures"),
            })

    # 3. Low confidence vs hallucination
    if "confidence_score" in df.columns and not df["confidence_score"].isna().all():
        low_confidence = df["confidence_score"] < 0.5
        is_hallucination = df["failure_type"] == "hallucination"

        phi = _compute_phi(low_confidence, is_hallucination)
        if abs(phi) > 0.1:
            correlations.append({
                "correlation_id": f"corr_{uuid.uuid4().hex[:8]}",
                "factor_a": "low_confidence (< 0.5)",
                "factor_b": "hallucination_failures",
                "correlation_strength": abs(phi),
                "interpretation": _interpret_correlation(phi, "low_confidence", "hallucination_failures"),
            })

    # 4. Low confidence vs confidence_mismatch
    if "confidence_score" in df.columns and not df["confidence_score"].isna().all():
        low_confidence = df["confidence_score"] < 0.5
        is_mismatch = df["failure_type"] == "confidence_mismatch"

        phi = _compute_phi(low_confidence, is_mismatch)
        if abs(phi) > 0.1:
            correlations.append({
                "correlation_id": f"corr_{uuid.uuid4().hex[:8]}",
                "factor_a": "low_confidence (< 0.5)",
                "factor_b": "confidence_mismatch_failures",
                "correlation_strength": abs(phi),
                "interpretation": _interpret_correlation(phi, "low_confidence", "confidence_mismatch_failures"),
            })

    # 5. Critical severity pattern
    if "failure_severity" in df.columns and not df["failure_severity"].isna().all():
        is_critical = df["failure_severity"] == "critical"
        has_failure = df["failure_type"].notna()

        phi = _compute_phi(is_critical, has_failure)
        if abs(phi) > 0.1:
            correlations.append({
                "correlation_id": f"corr_{uuid.uuid4().hex[:8]}",
                "factor_a": "critical_severity",
                "factor_b": "any_failure",
                "correlation_strength": abs(phi),
                "interpretation": _interpret_correlation(phi, "critical_severity", "failure_occurrence"),
            })

    return correlations


def _compute_phi(series_a: pd.Series, series_b: pd.Series) -> float:
    """
    Compute phi coefficient for two binary series.
    Phi measures association strength in 2x2 contingency tables.
    Range: [-1, 1], 0 = no association.
    """
    try:
        # Create 2x2 contingency table
        a = (series_a & series_b).sum()  # both true
        b = (series_a & ~series_b).sum()  # a true, b false
        c = (~series_a & series_b).sum()  # a false, b true
        d = (~series_a & ~series_b).sum()  # both false

        # Phi = (ad - bc) / sqrt((a+b)(c+d)(a+c)(b+d))
        numerator = (a * d) - (b * c)
        denominator = ((a + b) * (c + d) * (a + c) * (b + d)) ** 0.5

        if denominator == 0:
            return 0.0

        phi = numerator / denominator
        return min(1.0, max(-1.0, phi))  # Clamp to [-1, 1]

    except Exception as e:
        logger.warning(f"Error computing phi: {str(e)}")
        return 0.0


def _interpret_correlation(phi: float, factor_a: str, factor_b: str) -> str:
    """
    Generate human-readable interpretation of correlation.
    """
    abs_phi = abs(phi)
    direction = "positively" if phi > 0 else "negatively"

    if abs_phi > 0.5:
        strength = "strongly"
    elif abs_phi > 0.3:
        strength = "moderately"
    else:
        strength = "weakly"

    return f"{factor_a} is {strength} {direction} correlated with {factor_b}"
