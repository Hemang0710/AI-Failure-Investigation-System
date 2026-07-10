"""Authentication: bearer key required, hashed at rest, enforced on all routes."""

import sqlite3

import pytest

from auth import hash_api_key


PROTECTED_GETS = [
    "/api/v1/stats",
    "/api/v1/failures",
    "/api/v1/patterns",
    "/api/v1/models",
    "/api/v1/correlations",
]


@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_requires_auth(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_valid_key_allowed(client, auth_headers, path):
    assert client.get(path, headers=auth_headers).status_code == 200


def test_rejects_unknown_key(client):
    resp = client.get("/api/v1/stats", headers={"Authorization": "Bearer sk-not-a-real-key"})
    assert resp.status_code == 401


def test_rejects_old_demo_key(client):
    resp = client.get("/api/v1/stats", headers={"Authorization": "Bearer sk-demo-12345"})
    assert resp.status_code == 401


def test_wrong_scheme_rejected(client, api_key):
    resp = client.get("/api/v1/stats", headers={"Authorization": f"Basic {api_key}"})
    assert resp.status_code in (401, 403)


def test_unauthorized_sets_www_authenticate(client):
    resp = client.get("/api/v1/stats")
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_key_stored_hashed_not_plaintext(api_key):
    # Read the seeded key straight from the test database file.
    from conftest import _DB_PATH  # type: ignore

    con = sqlite3.connect(_DB_PATH)
    try:
        rows = con.execute("SELECT key_hash FROM api_keys").fetchall()
    finally:
        con.close()

    hashes = {r[0] for r in rows}
    assert hash_api_key(api_key) in hashes
    assert api_key not in hashes  # plaintext never stored
    assert all(len(h) == 64 for h in hashes)  # sha256 hex
