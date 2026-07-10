"""Event ingestion: happy path, attribution, validation, and redaction at rest."""

import sqlite3

import pytest

from conftest import make_event


def test_ingest_accepts_valid_batch(client, auth_headers):
    resp = client.post(
        "/api/v1/events",
        headers=auth_headers,
        json={"events": [make_event(model_name="ingest-ok-model")]},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["event_count"] == 1
    assert body["batch_id"].startswith("batch_")


def test_ingest_requires_auth(client):
    resp = client.post("/api/v1/events", json={"events": [make_event()]})
    assert resp.status_code == 401


def test_ingested_event_is_queryable(client, auth_headers):
    marker = "queryable-model-xyz"
    client.post("/api/v1/events", headers=auth_headers, json={"events": [make_event(model_name=marker)]})
    resp = client.get("/api/v1/failures", headers=auth_headers, params={"model": marker, "hours": 720})
    assert resp.status_code == 200
    failures = resp.json()["failures"]
    assert any(f["model_name"] == marker for f in failures)


@pytest.mark.parametrize(
    "bad_batch",
    [
        {"events": []},                                        # empty batch
        {"events": [make_event(prompt="x" * 100_001)]},        # prompt over cap
        {"events": [make_event(model_name="m" * 300)]},        # model_name too long
        {"events": [make_event(failure_type="not_a_type")]},   # invalid enum
        {"events": [make_event(confidence_score=1.7)]},        # out of range
        {"events": [make_event(tags=["t"] * 51)]},             # too many tags
    ],
)
def test_ingest_rejects_invalid_payloads(client, auth_headers, bad_batch):
    resp = client.post("/api/v1/events", headers=auth_headers, json=bad_batch)
    assert resp.status_code == 422


def test_pii_redacted_before_storage(client, auth_headers):
    from conftest import _DB_PATH  # type: ignore

    marker = "redaction-model-abc"
    resp = client.post(
        "/api/v1/events",
        headers=auth_headers,
        json={"events": [make_event(
            model_name=marker,
            prompt="email me at leak@example.com or call 415-555-0132",
            response="card 4111 1111 1111 1111",
        )]},
    )
    assert resp.status_code == 202

    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT prompt, response FROM failure_events WHERE model_name = ?", (marker,)
        ).fetchone()
    finally:
        con.close()

    stored = " ".join(row)
    assert "leak@example.com" not in stored
    assert "4111 1111 1111 1111" not in stored
    assert "415-555-0132" not in stored
    assert "[REDACTED_EMAIL]" in stored
