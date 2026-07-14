"""Webhook alerting for new failure patterns and failure-rate spikes.

Set ALERT_WEBHOOK_URL to enable. Slack incoming-webhook URLs get a Slack
payload ({"text": ...}); any other URL gets a structured JSON payload, so a
generic receiver (PagerDuty event orchestration, n8n, a custom endpoint)
works too. Alerts never raise: a failed delivery is logged and dropped.

Environment:
    ALERT_WEBHOOK_URL              destination (unset = alerting disabled)
    ALERT_COOLDOWN_MINUTES         min minutes between alerts with the same
                                   key, so a flapping model doesn't spam (60)
    ALERT_FAILURE_RATE_THRESHOLD   per-model failure rate that counts as a
                                   spike (0.25)
    ALERT_MIN_EVENTS               events a model needs in the window before
                                   its rate can alert (20)
    ALERT_WINDOW_HOURS             spike detection window (1)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# key -> last sent time; module-level so cooldowns span requests
_last_sent: dict = {}


def _webhook_url() -> Optional[str]:
    return os.getenv("ALERT_WEBHOOK_URL") or None


def _cooldown() -> timedelta:
    return timedelta(minutes=float(os.getenv("ALERT_COOLDOWN_MINUTES", "60")))


def reset_cooldowns() -> None:
    """Testing hook."""
    _last_sent.clear()


async def _post(url: str, payload: dict) -> bool:
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    return True


def _build_payload(url: str, kind: str, message: str, data: Optional[dict]) -> dict:
    if "hooks.slack.com" in url:
        text = f":rotating_light: *{kind.replace('_', ' ').title()}*\n{message}"
        if data:
            details = "\n".join(f"• {k}: {v}" for k, v in data.items())
            text = f"{text}\n{details}"
        return {"text": text}
    return {
        "kind": kind,
        "message": message,
        "data": data or {},
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "ai-failure-investigation-system",
    }


async def send_alert(kind: str, key: str, message: str, data: Optional[dict] = None) -> bool:
    """Deliver one alert, subject to per-key cooldown. Returns True if sent."""
    url = _webhook_url()
    if not url:
        return False

    now = datetime.now(timezone.utc)
    last = _last_sent.get(key)
    if last is not None and now - last < _cooldown():
        logger.debug(f"Alert '{key}' suppressed by cooldown")
        return False

    try:
        await _post(url, _build_payload(url, kind, message, data))
        _last_sent[key] = now
        logger.info(f"Alert sent: {key}")
        return True
    except Exception as e:
        logger.error(f"Failed to deliver alert '{key}': {str(e)}")
        return False


async def check_failure_rate_spikes(db: AsyncSession) -> int:
    """Alert on models whose recent failure rate crosses the threshold.

    Returns the number of alerts sent. Cheap enough to run after every
    pattern analysis; the per-key cooldown keeps repeats quiet.
    """
    if not _webhook_url():
        return 0

    threshold = float(os.getenv("ALERT_FAILURE_RATE_THRESHOLD", "0.25"))
    min_events = int(os.getenv("ALERT_MIN_EVENTS", "20"))
    window_hours = float(os.getenv("ALERT_WINDOW_HOURS", "1"))

    # Deferred import: models depends on database.Base
    from models import FailureEvent

    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    stmt = select(
        FailureEvent.model_name,
        func.count().label("total"),
        func.count(
            case((FailureEvent.failure_type.isnot(None), 1))
        ).label("failures"),
    ).where(FailureEvent.timestamp >= since).group_by(FailureEvent.model_name)

    rows = (await db.execute(stmt)).mappings().all()

    sent = 0
    for row in rows:
        total, failures = row["total"], row["failures"]
        if total < min_events:
            continue
        rate = failures / total
        if rate < threshold:
            continue
        delivered = await send_alert(
            kind="failure_rate_spike",
            key=f"spike:{row['model_name']}",
            message=(
                f"{row['model_name']} failure rate is {rate:.0%} over the last "
                f"{window_hours:g}h ({failures}/{total} events), above the "
                f"{threshold:.0%} threshold."
            ),
            data={
                "model_name": row["model_name"],
                "failure_rate": round(rate, 4),
                "failures": failures,
                "total_events": total,
                "window_hours": window_hours,
            },
        )
        sent += 1 if delivered else 0
    return sent
