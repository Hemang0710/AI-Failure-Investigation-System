"""Webhook alerting: payloads, cooldowns, spike detection, pattern hook."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import alerting
from database import AsyncSessionLocal
from models import FailureEvent


@pytest.fixture
def captured_posts(monkeypatch):
    """Enable alerting against a fake webhook and capture deliveries."""
    posts = []

    async def fake_post(url, payload):
        posts.append((url, payload))
        return True

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setattr(alerting, "_post", fake_post)
    alerting.reset_cooldowns()
    yield posts
    alerting.reset_cooldowns()


def test_disabled_without_webhook_url(monkeypatch):
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    sent = asyncio.run(alerting.send_alert("new_pattern", "k", "msg"))
    assert sent is False


def test_generic_payload_structure(captured_posts):
    sent = asyncio.run(alerting.send_alert(
        "new_pattern", "pattern:x:y", "Something happened", {"model_name": "m"}
    ))
    assert sent is True
    url, payload = captured_posts[0]
    assert payload["kind"] == "new_pattern"
    assert payload["message"] == "Something happened"
    assert payload["data"] == {"model_name": "m"}
    assert payload["source"] == "ai-failure-investigation-system"


def test_slack_payload_uses_text(monkeypatch, captured_posts):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/x")
    asyncio.run(alerting.send_alert("failure_rate_spike", "k", "Rate is up", {"rate": 0.5}))
    _, payload = captured_posts[0]
    assert set(payload.keys()) == {"text"}
    assert "Rate is up" in payload["text"]
    assert "rate: 0.5" in payload["text"]


def test_cooldown_suppresses_repeat_alerts(captured_posts):
    assert asyncio.run(alerting.send_alert("new_pattern", "same-key", "first")) is True
    assert asyncio.run(alerting.send_alert("new_pattern", "same-key", "second")) is False
    assert asyncio.run(alerting.send_alert("new_pattern", "other-key", "third")) is True
    assert len(captured_posts) == 2


def test_delivery_failure_returns_false(monkeypatch):
    async def failing_post(url, payload):
        raise RuntimeError("connection refused")

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setattr(alerting, "_post", failing_post)
    alerting.reset_cooldowns()
    assert asyncio.run(alerting.send_alert("new_pattern", "k", "msg")) is False


async def _seed_model_events(model_name: str, failures: int, successes: int):
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        for i in range(failures + successes):
            db.add(FailureEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}", user_id=1,
                timestamp=now - timedelta(minutes=10),
                model_name=model_name,
                failure_type="timeout" if i < failures else None,
                failure_severity="high" if i < failures else None,
            ))
        await db.commit()


def test_spike_detection_alerts_on_hot_model(client, monkeypatch, captured_posts):
    monkeypatch.setenv("ALERT_FAILURE_RATE_THRESHOLD", "0.25")
    monkeypatch.setenv("ALERT_MIN_EVENTS", "20")

    hot = f"spiking-{uuid.uuid4().hex[:6]}"
    cold = f"steady-{uuid.uuid4().hex[:6]}"

    async def run():
        await _seed_model_events(hot, failures=10, successes=10)   # 50% rate
        await _seed_model_events(cold, failures=1, successes=24)   # 4% rate
        async with AsyncSessionLocal() as db:
            return await alerting.check_failure_rate_spikes(db)

    sent = asyncio.run(run())
    assert sent == 1
    alerted_models = {p[1]["data"]["model_name"] for p in captured_posts}
    assert hot in alerted_models
    assert cold not in alerted_models


def test_spike_ignores_models_below_min_events(client, monkeypatch, captured_posts):
    monkeypatch.setenv("ALERT_FAILURE_RATE_THRESHOLD", "0.25")
    monkeypatch.setenv("ALERT_MIN_EVENTS", "20")

    tiny = f"tiny-{uuid.uuid4().hex[:6]}"

    async def run():
        await _seed_model_events(tiny, failures=5, successes=0)  # 100% but only 5 events
        async with AsyncSessionLocal() as db:
            return await alerting.check_failure_rate_spikes(db)

    asyncio.run(run())
    alerted_models = {p[1]["data"].get("model_name") for p in captured_posts}
    assert tiny not in alerted_models


def test_new_pattern_triggers_alert(client, captured_posts):
    from services.pattern_engine import run_pattern_analysis

    model = f"alert-pattern-{uuid.uuid4().hex[:6]}"

    async def run():
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            for _ in range(4):
                db.add(FailureEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}", user_id=1,
                    timestamp=now - timedelta(hours=1),
                    model_name=model, failure_type="hallucination",
                    failure_severity="high", confidence_score=0.3,
                ))
            await db.commit()
            await run_pattern_analysis(db, hours=24, min_occurrences=3)

    asyncio.run(run())
    pattern_alerts = [
        p for _, p in captured_posts
        if p.get("kind") == "new_pattern" and p["data"].get("model_name") == model
    ]
    assert len(pattern_alerts) == 1
    assert pattern_alerts[0]["data"].get("suggested_remediation")
