"""Pattern engine: timezone normalization and end-to-end pattern creation."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select

from database import AsyncSessionLocal
from models import FailureEvent, Pattern
from services.pattern_engine import _to_utc_datetime, run_pattern_analysis


def test_to_utc_datetime_localizes_naive():
    out = _to_utc_datetime(pd.Timestamp("2026-07-05 08:44:17"))
    assert out.tzinfo is not None
    assert out.utcoffset() == timedelta(0)


def test_to_utc_datetime_converts_aware():
    out = _to_utc_datetime(pd.Timestamp("2026-07-05 08:44:17", tz="America/New_York"))
    assert out.tzinfo is not None
    assert out.utcoffset() == timedelta(0)


async def _seed_and_analyze(model_name: str):
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        for _ in range(4):  # >= min_occurrences (3)
            db.add(FailureEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}", user_id=1,
                timestamp=now - timedelta(hours=1),
                model_name=model_name, failure_type="hallucination",
                failure_severity="high", confidence_score=0.3,
            ))
        await db.commit()

        count = await run_pattern_analysis(db, hours=24, min_occurrences=3)

        pattern = (await db.execute(
            select(Pattern).where(Pattern.model_name == model_name)
        )).scalar_one_or_none()
    return count, pattern


def test_analysis_creates_pattern_for_clustered_failures():
    model = f"pattern-model-{uuid.uuid4().hex[:6]}"
    count, pattern = asyncio.run(_seed_and_analyze(model))
    assert count >= 1
    assert pattern is not None
    assert pattern.occurrence_count >= 4
    assert pattern.first_seen is not None
    assert pattern.suggested_remediation  # remediation text was generated
