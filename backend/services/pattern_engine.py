import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import pandas as pd
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from models import FailureEvent, Pattern

logger = logging.getLogger(__name__)


def _to_utc_datetime(value) -> datetime:
    """Normalize a pandas/py timestamp to a tz-aware UTC datetime.

    pandas drops tz info when aggregating the tz-aware event timestamps, which
    asyncpg then rejects for a TIMESTAMP WITH TIME ZONE column. Events are
    stored in UTC, so a naive value is localized to UTC.
    """
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.to_pydatetime()


async def run_pattern_analysis(
    db: AsyncSession,
    hours: int = 24,
    min_occurrences: int = 3,
) -> int:
    """
    Main entry point for pattern analysis.
    Analyzes FailureEvent rows from the last N hours,
    creates/updates Pattern rows via groupby aggregation.
    Returns count of patterns created or updated.
    """
    try:
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Load events into DataFrame
        df = await _load_events_as_dataframe(db, time_threshold)
        if df.empty:
            logger.info(f"No events in last {hours} hours for pattern analysis")
            return 0

        # Compute pattern groups
        pattern_groups = _compute_pattern_groups(df, min_occurrences)
        if pattern_groups.empty:
            logger.info(f"No patterns with >= {min_occurrences} occurrences")
            return 0

        # Upsert each pattern
        pattern_count = 0
        for _, row in pattern_groups.iterrows():
            failure_type = row["failure_type"]
            model_name = row["model_name"]

            # Build remediation suggestion
            remediation = _generate_remediation(
                failure_type=failure_type,
                avg_confidence=float(row.get("avg_confidence", 0)),
                avg_retrieval_score=float(row.get("avg_retrieval_score", 0)),
                occurrence_count=int(row["occurrence_count"]),
            )

            stats = {
                "occurrence_count": int(row["occurrence_count"]),
                "unique_users_affected": int(row.get("unique_users_affected", 1)),
                "first_seen": _to_utc_datetime(row["first_seen"]),
                "last_seen": _to_utc_datetime(row["last_seen"]),
                "average_confidence": float(row.get("avg_confidence", 0)),
                "average_latency_ms": float(row.get("avg_latency_ms", 0)),
                "average_retrieval_score": float(row.get("avg_retrieval_score", 0)) if pd.notna(row.get("avg_retrieval_score")) else None,
                "severity_breakdown": row.get("severity_breakdown", {}),
            }

            await _upsert_pattern(db, failure_type, model_name, stats, remediation)
            pattern_count += 1

        logger.info(f"Pattern analysis complete: {pattern_count} patterns created/updated")
        return pattern_count

    except Exception as e:
        logger.error(f"Pattern analysis error: {str(e)}", exc_info=True)
        return 0


async def _load_events_as_dataframe(
    db: AsyncSession,
    since: datetime,
) -> pd.DataFrame:
    """
    Loads FailureEvent rows from since timestamp as a pandas DataFrame.
    Executes a single SELECT query with all needed columns.
    """
    stmt = select(
        FailureEvent.id,
        FailureEvent.event_id,
        FailureEvent.failure_type,
        FailureEvent.model_name,
        FailureEvent.failure_severity,
        FailureEvent.confidence_score,
        FailureEvent.latency_ms,
        FailureEvent.retrieval_score,
        FailureEvent.user_id,
        FailureEvent.timestamp,
    ).where(FailureEvent.timestamp >= since)

    result = await db.execute(stmt)
    rows = result.mappings().all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    return df


def _compute_pattern_groups(
    df: pd.DataFrame,
    min_occurrences: int,
) -> pd.DataFrame:
    """
    Groups by (failure_type, model_name) and computes aggregates.
    Filters groups with occurrence_count < min_occurrences.
    Returns DataFrame with one row per pattern group.
    """
    if df.empty:
        return pd.DataFrame()

    # Group by failure_type and model_name
    grouped = df.groupby(["failure_type", "model_name"], as_index=False).agg({
        "id": "count",
        "user_id": "nunique",
        "timestamp": ["min", "max"],
        "confidence_score": "mean",
        "latency_ms": "mean",
        "retrieval_score": "mean",
        "failure_severity": lambda x: x.value_counts().to_dict(),
    }).reset_index(drop=True)

    # Flatten multi-level columns from agg
    grouped.columns = [
        "failure_type", "model_name", "occurrence_count", "unique_users_affected",
        "first_seen", "last_seen", "avg_confidence", "avg_latency_ms",
        "avg_retrieval_score", "severity_breakdown"
    ]

    # Filter by min occurrences
    grouped = grouped[grouped["occurrence_count"] >= min_occurrences].copy()

    # Ensure severity_breakdown is a dict
    grouped["severity_breakdown"] = grouped["severity_breakdown"].apply(
        lambda x: x.to_dict() if hasattr(x, "to_dict") else x if isinstance(x, dict) else {}
    )

    return grouped


def _generate_remediation(
    failure_type: str,
    avg_confidence: float,
    avg_retrieval_score: float,
    occurrence_count: int,
) -> str:
    """
    Generates rule-based remediation text based on failure type and metrics.
    """
    remediation_map = {
        "hallucination": lambda: (
            "High-confidence hallucinations detected. Add fact-checking prompts or chain-of-thought verification. "
            "Consider reducing temperature or adding retrieval grounding."
            if avg_confidence > 0.8 else
            "Low-confidence hallucinations detected. Add confidence threshold gating before returning responses to users."
        ),
        "empty_response": lambda: (
            "Model returning empty responses. Check token limits, verify prompt length is within model context window, "
            "add retry logic with exponential backoff."
        ),
        "timeout": lambda: (
            f"Systematic timeouts detected across {occurrence_count} events. "
            "Increase timeout thresholds, implement streaming responses, or reduce model complexity."
        ),
        "retrieval_failure": lambda: (
            f"Poor retrieval quality (avg score: {avg_retrieval_score:.2f}). "
            "Improve vector index quality, adjust query expansion, or enhance chunking strategy."
            if avg_retrieval_score is not None and avg_retrieval_score < 0.5 else
            "Retrieval failures detected. Verify vector store connectivity and index health."
        ),
        "confidence_mismatch": lambda: (
            "Confidence scores not matching actual quality. Re-calibrate confidence estimation model "
            "or add output validation layer with manual review threshold."
        ),
        "malformed_response": lambda: (
            "Model returning malformed responses. Add response validation, implement structured output validation, "
            "or add post-processing normalization."
        ),
        "semantic_error": lambda: (
            "Semantic errors in responses. Review prompt clarity, add few-shot examples, "
            "or implement semantic validation with fallback strategies."
        ),
        "rate_limited": lambda: (
            f"Rate limiting observed across {occurrence_count} events. Implement request batching, "
            "backoff strategies, or upgrade API tier."
        ),
        "token_limit": lambda: (
            "Token limit exceeded errors. Reduce context window size, implement sliding window summarization, "
            "or optimize prompt engineering."
        ),
    }

    generator = remediation_map.get(failure_type, lambda: "Monitor this failure pattern closely.")
    return generator()


async def _upsert_pattern(
    db: AsyncSession,
    failure_type: str,
    model_name: str,
    stats: dict,
    remediation: str,
) -> Optional[Pattern]:
    """
    Upserts a Pattern row.
    Looks up existing pattern by (failure_type, model_name).
    If exists: update stats; if not: create new with pattern_id.
    """
    try:
        # Check if pattern exists
        stmt = select(Pattern).where(
            and_(
                Pattern.failure_type == failure_type,
                Pattern.model_name == model_name,
            )
        )
        result = await db.execute(stmt)
        existing_pattern = result.scalar_one_or_none()

        if existing_pattern:
            # Update existing pattern
            existing_pattern.occurrence_count = stats["occurrence_count"]
            existing_pattern.unique_users_affected = stats["unique_users_affected"]
            existing_pattern.last_seen = stats["last_seen"]
            existing_pattern.average_confidence = stats["average_confidence"]
            existing_pattern.average_latency_ms = stats["average_latency_ms"]
            existing_pattern.average_retrieval_score = stats.get("average_retrieval_score")
            existing_pattern.severity_breakdown = stats.get("severity_breakdown", {})
            existing_pattern.suggested_remediation = remediation
            existing_pattern.updated_at = datetime.now(timezone.utc)
            await db.merge(existing_pattern)
        else:
            # Create new pattern
            pattern_id = f"pat_{uuid.uuid4().hex[:8]}"
            new_pattern = Pattern(
                pattern_id=pattern_id,
                failure_type=failure_type,
                model_name=model_name,
                occurrence_count=stats["occurrence_count"],
                unique_users_affected=stats["unique_users_affected"],
                first_seen=stats["first_seen"],
                last_seen=stats["last_seen"],
                average_confidence=stats["average_confidence"],
                average_latency_ms=stats["average_latency_ms"],
                average_retrieval_score=stats.get("average_retrieval_score"),
                severity_breakdown=stats.get("severity_breakdown", {}),
                suggested_remediation=remediation,
                remediation_tested=False,
                remediation_effectiveness=None,
            )
            db.add(new_pattern)

        await db.commit()
        logger.debug(f"Pattern upserted: {failure_type} on {model_name}")
        return existing_pattern or new_pattern

    except Exception as e:
        logger.error(f"Upsert pattern error: {str(e)}", exc_info=True)
        return None
