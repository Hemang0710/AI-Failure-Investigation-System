"""Data-retention purge: removes expired events (and their feedback), keeps recent."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from database import AsyncSessionLocal
from models import FailureEvent, Feedback
import retention


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _run_purge_scenario(retention_days: int):
    old_id = _unique("evt_old")
    new_id = _unique("evt_new")

    async with AsyncSessionLocal() as db:
        old = FailureEvent(
            event_id=old_id, user_id=1,
            timestamp=datetime.now(timezone.utc) - timedelta(days=40),
            model_name="retention-test", failure_type="hallucination",
        )
        new = FailureEvent(
            event_id=new_id, user_id=1,
            timestamp=datetime.now(timezone.utc) - timedelta(days=1),
            model_name="retention-test", failure_type="hallucination",
        )
        db.add_all([old, new])
        await db.flush()
        # Feedback on the OLD event exercises the FK-ordering path.
        db.add(Feedback(feedback_id=_unique("fb"), event_id=old.id, user_id=1, is_actual_failure=True))
        await db.commit()

        removed = await retention.purge_old_events(db, retention_days=retention_days)

        surviving = set(
            (await db.execute(
                select(FailureEvent.event_id).where(FailureEvent.model_name == "retention-test")
            )).scalars().all()
        )
        orphan_feedback = await db.scalar(
            select(func.count()).select_from(Feedback).where(
                ~Feedback.event_id.in_(select(FailureEvent.id))
            )
        )
    return removed, surviving, old_id, new_id, orphan_feedback


def test_purge_removes_old_keeps_recent():
    removed, surviving, old_id, new_id, orphan_feedback = asyncio.run(_run_purge_scenario(30))
    assert removed == 1
    assert old_id not in surviving
    assert new_id in surviving
    assert orphan_feedback == 0  # feedback for the deleted event was removed too


def test_zero_retention_is_noop():
    removed, surviving, old_id, new_id, _ = asyncio.run(_run_purge_scenario(0))
    assert removed == 0
    assert old_id in surviving and new_id in surviving
