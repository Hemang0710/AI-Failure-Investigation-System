"""Pattern JSONL export: eval-set download of a pattern's failing events."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from database import AsyncSessionLocal
from models import FailureEvent, Pattern
from services.pattern_engine import run_pattern_analysis


def _seed_pattern(model_name: str) -> str:
    """Create clustered failures + a success, analyze, return pattern_id."""
    async def run():
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            for i in range(4):
                db.add(FailureEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}", user_id=1,
                    timestamp=now - timedelta(hours=1),
                    model_name=model_name, failure_type="hallucination",
                    failure_severity="high", confidence_score=0.3,
                    prompt=f"prompt {i}", response=f"wrong answer {i}",
                ))
            # A success on the same model must not leak into the export.
            db.add(FailureEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}", user_id=1,
                timestamp=now - timedelta(hours=1),
                model_name=model_name, failure_type=None,
                prompt="fine", response="fine",
            ))
            await db.commit()
            await run_pattern_analysis(db, hours=24, min_occurrences=3)
            pattern = (await db.execute(
                select(Pattern).where(Pattern.model_name == model_name)
            )).scalar_one()
            return pattern.pattern_id

    return asyncio.run(run())


def test_export_returns_jsonl_of_failing_events(client, auth_headers):
    model = f"export-model-{uuid.uuid4().hex[:6]}"
    pattern_id = _seed_pattern(model)

    resp = client.get(f"/api/v1/patterns/{pattern_id}/export", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert f'{pattern_id}.jsonl' in resp.headers["content-disposition"]

    lines = [json.loads(line) for line in resp.text.splitlines() if line]
    assert resp.headers["x-event-count"] == str(len(lines))
    assert len(lines) == 4
    for line in lines:
        assert line["model_name"] == model
        assert line["failure_type"] == "hallucination"
        assert line["prompt"].startswith("prompt")


def test_export_respects_limit(client, auth_headers):
    model = f"export-limit-{uuid.uuid4().hex[:6]}"
    pattern_id = _seed_pattern(model)

    resp = client.get(
        f"/api/v1/patterns/{pattern_id}/export",
        headers=auth_headers,
        params={"limit": 2},
    )
    assert resp.status_code == 200
    assert len(resp.text.splitlines()) == 2


def test_export_unknown_pattern_404(client, auth_headers):
    resp = client.get("/api/v1/patterns/pat_doesnotexist/export", headers=auth_headers)
    assert resp.status_code == 404


def test_export_requires_auth(client):
    resp = client.get("/api/v1/patterns/pat_whatever/export")
    assert resp.status_code == 401
