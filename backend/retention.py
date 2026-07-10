"""Data retention: periodically purge failure events past their retention window.

Keeping raw prompts/responses indefinitely is a liability even after redaction,
so operators can set a maximum age. Deletion is opt-in and disabled by default
(DATA_RETENTION_DAYS=0) so upgrading never silently drops existing data.

Configuration (environment):
  DATA_RETENTION_DAYS           events older than this are deleted (0 = keep forever)
  RETENTION_SWEEP_INTERVAL_HOURS how often the background sweep runs (default: 24)
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import FailureEvent, Feedback

logger = logging.getLogger(__name__)

DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "0"))
RETENTION_SWEEP_INTERVAL_HOURS = float(os.getenv("RETENTION_SWEEP_INTERVAL_HOURS", "24"))


async def purge_old_events(db: AsyncSession, retention_days: int) -> int:
    """Delete events (and their feedback) older than `retention_days`.

    Returns the number of events removed. A non-positive retention window is a
    no-op. Feedback rows are removed first to satisfy the foreign key.
    """
    if retention_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    old_event_ids = select(FailureEvent.id).where(FailureEvent.timestamp < cutoff)

    await db.execute(delete(Feedback).where(Feedback.event_id.in_(old_event_ids)))
    result = await db.execute(
        delete(FailureEvent).where(FailureEvent.timestamp < cutoff)
    )
    await db.commit()
    return result.rowcount or 0


async def retention_loop() -> None:
    """Run purge_old_events on an interval until cancelled."""
    interval_seconds = max(60.0, RETENTION_SWEEP_INTERVAL_HOURS * 3600)
    logger.info(
        "Retention sweep active: deleting events older than %d days every %.1f h",
        DATA_RETENTION_DAYS,
        RETENTION_SWEEP_INTERVAL_HOURS,
    )
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            async with AsyncSessionLocal() as db:
                removed = await purge_old_events(db, DATA_RETENTION_DAYS)
            if removed:
                logger.info("Retention sweep removed %d expired events", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Retention sweep failed; will retry next interval")
