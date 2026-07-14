"""Task-aware ingestion, cost estimation, and the /recommendations ranking."""

import sqlite3

from conftest import make_event


def _ingest(client, auth_headers, events):
    resp = client.post("/api/v1/events", headers=auth_headers, json={"events": events})
    assert resp.status_code == 202, resp.text
    return resp


def test_success_event_without_failure_type_is_accepted(client, auth_headers):
    event = make_event(model_name="success-model-abc")
    del event["failure_type"]
    del event["failure_severity"]
    _ingest(client, auth_headers, [event])

    # Success events must not surface in the failures view.
    resp = client.get(
        "/api/v1/failures",
        headers=auth_headers,
        params={"model": "success-model-abc", "hours": 720},
    )
    assert resp.status_code == 200
    assert resp.json()["failures"] == []


def test_invalid_task_type_rejected(client, auth_headers):
    resp = client.post(
        "/api/v1/events",
        headers=auth_headers,
        json={"events": [make_event(task_type="not_a_task")]},
    )
    assert resp.status_code == 422


def test_cost_estimated_from_tokens(client, auth_headers):
    from conftest import _DB_PATH  # type: ignore

    marker = "gpt-4o-cost-test"
    _ingest(client, auth_headers, [make_event(
        model_name=marker,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )])

    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT cost_usd, input_tokens, output_tokens FROM failure_events WHERE model_name = ?",
            (marker,),
        ).fetchone()
    finally:
        con.close()

    # gpt-4o prefix: $2.50/M input + $10.00/M output
    assert row == (12.5, 1_000_000, 1_000_000)


def test_explicit_cost_wins_over_estimate(client, auth_headers):
    from conftest import _DB_PATH  # type: ignore

    marker = "gpt-4o-explicit-cost"
    _ingest(client, auth_headers, [make_event(
        model_name=marker,
        input_tokens=1_000_000,
        cost_usd=0.42,
    )])

    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT cost_usd FROM failure_events WHERE model_name = ?", (marker,)
        ).fetchone()
    finally:
        con.close()

    assert row == (0.42,)


def _seed_task_traffic(client, auth_headers):
    """Two models on 'translation': rec-good (10/10 ok), rec-bad (5/10 fail)."""
    events = []
    for i in range(10):
        good = make_event(model_name="rec-good", task_type="translation")
        del good["failure_type"]
        del good["failure_severity"]
        events.append(good)

        bad = make_event(model_name="rec-bad", task_type="translation")
        if i >= 5:
            del bad["failure_type"]
            del bad["failure_severity"]
        events.append(bad)
    _ingest(client, auth_headers, events)


def test_recommendations_rank_by_failure_rate(client, auth_headers):
    _seed_task_traffic(client, auth_headers)

    resp = client.get(
        "/api/v1/recommendations",
        headers=auth_headers,
        params={"task_type": "translation", "hours": 720, "min_events": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["min_events"] == 5
    assert len(body["tasks"]) == 1

    task = body["tasks"][0]
    assert task["task_type"] == "translation"
    assert task["recommended_model"] == "rec-good"

    by_name = {m["model_name"]: m for m in task["ranked_models"]}
    assert task["ranked_models"][0]["model_name"] == "rec-good"
    assert by_name["rec-good"]["failure_rate"] == 0.0
    assert by_name["rec-good"]["success_rate"] == 1.0
    assert by_name["rec-bad"]["failure_rate"] == 0.5
    assert by_name["rec-bad"]["top_failure_type"] == "hallucination"
    assert all(m["sample_sufficient"] for m in task["ranked_models"])
    assert task["caveat"] is None


def test_recommendations_caveat_when_sample_too_small(client, auth_headers):
    # Traffic seeded by the ranking test (10 events/model) is below this bar.
    _seed_task_traffic(client, auth_headers)

    resp = client.get(
        "/api/v1/recommendations",
        headers=auth_headers,
        params={"task_type": "translation", "hours": 720, "min_events": 1000},
    )
    assert resp.status_code == 200
    task = resp.json()["tasks"][0]
    assert task["recommended_model"] is None
    assert task["caveat"] is not None
    assert all(not m["sample_sufficient"] for m in task["ranked_models"])


def test_recommendations_requires_auth(client):
    resp = client.get("/api/v1/recommendations")
    assert resp.status_code == 401


def test_events_without_task_type_are_excluded(client, auth_headers):
    _ingest(client, auth_headers, [make_event(model_name="untasked-model-xyz")])

    resp = client.get(
        "/api/v1/recommendations",
        headers=auth_headers,
        params={"hours": 720},
    )
    assert resp.status_code == 200
    models_seen = {
        m["model_name"] for t in resp.json()["tasks"] for m in t["ranked_models"]
    }
    assert "untasked-model-xyz" not in models_seen


def test_pricing_prefix_matching():
    from pricing import estimate_cost, lookup_pricing

    # Longest prefix wins: mini pricing, not gpt-4o pricing.
    assert lookup_pricing("gpt-4o-mini-2024-07-18") == (0.15, 0.60)
    assert lookup_pricing("GPT-4o-2024-08-06") == (2.50, 10.00)
    assert lookup_pricing("totally-unknown-model") is None

    assert estimate_cost("unknown", 1000, 1000) is None
    assert estimate_cost("gpt-4o", None, None) is None
    assert estimate_cost("gpt-4o", 1_000_000, 0) == 2.50
