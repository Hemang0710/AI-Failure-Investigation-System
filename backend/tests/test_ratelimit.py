"""Unit tests for the rate-limiting dependency and client keying."""

import asyncio
import types

import pytest
from fastapi import HTTPException

import ratelimit


def _fake_request(auth: str | None = None, host: str = "10.0.0.1"):
    headers = {"authorization": auth} if auth else {}
    return types.SimpleNamespace(headers=headers, client=types.SimpleNamespace(host=host))


def test_client_key_distinguishes_tokens():
    a = ratelimit._client_key(_fake_request(auth="Bearer key-aaa"))
    b = ratelimit._client_key(_fake_request(auth="Bearer key-bbb"))
    assert a != b
    assert a.startswith("key:")


def test_client_key_falls_back_to_ip():
    key = ratelimit._client_key(_fake_request(auth=None, host="203.0.113.5"))
    assert key == "ip:203.0.113.5"


def test_limiter_allows_then_blocks(monkeypatch):
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_ENABLED", True)
    dep = ratelimit.rate_limiter("2/minute", "unit-allow-block")
    req = _fake_request(auth="Bearer unit-test-token-1")

    # First two calls pass, the third is rejected with 429 + Retry-After.
    asyncio.run(dep(req))
    asyncio.run(dep(req))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dep(req))
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


def test_limiter_buckets_are_per_client(monkeypatch):
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_ENABLED", True)
    dep = ratelimit.rate_limiter("1/minute", "unit-per-client")

    asyncio.run(dep(_fake_request(auth="Bearer client-A")))
    # A different client still has its full allowance.
    asyncio.run(dep(_fake_request(auth="Bearer client-B")))
    # A's bucket is now exhausted.
    with pytest.raises(HTTPException):
        asyncio.run(dep(_fake_request(auth="Bearer client-A")))


def test_disabled_limiter_is_noop(monkeypatch):
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_ENABLED", False)
    dep = ratelimit.rate_limiter("1/minute", "unit-disabled")
    req = _fake_request(auth="Bearer whatever")
    for _ in range(5):
        asyncio.run(dep(req))  # never raises
