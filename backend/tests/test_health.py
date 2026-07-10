"""Health endpoint is open and reports component status."""


def test_health_open_without_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"healthy", "degraded"}
    assert body["components"]["database"] == "healthy"
