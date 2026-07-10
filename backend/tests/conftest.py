"""Shared pytest fixtures.

The app builds its database engine and rate limiters from environment variables
at import time, so those must be set *before* `main` is imported. Tests run
against a throwaway SQLite database with rate limiting and the background
pattern-analysis trigger disabled for determinism.
"""

import os
import tempfile
import pathlib

import pytest

TEST_API_KEY = "sk-test-suite-0123456789abcdefABCDEF"

_TMPDIR = tempfile.mkdtemp(prefix="aifis-tests-")
_DB_PATH = pathlib.Path(_TMPDIR) / "test.db"

os.environ["ASYNC_DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}"
os.environ["BOOTSTRAP_API_KEY"] = TEST_API_KEY
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["PATTERN_ANALYSIS_ON_INGEST"] = "false"
os.environ.setdefault("PII_REDACTION_ENABLED", "true")

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402


@pytest.fixture(scope="session")
def client():
    # Entering the context manager runs the lifespan, which seeds the API key.
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def api_key() -> str:
    return TEST_API_KEY


@pytest.fixture(scope="session")
def auth_headers(api_key) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def make_event(**overrides) -> dict:
    """A minimal valid ingestion event; override any field."""
    event = {
        "timestamp": "2026-07-10T12:00:00Z",
        "model_name": "gpt-4",
        "provider": "openai",
        "prompt": "What is the capital of France?",
        "response": "The capital is London.",
        "confidence_score": 0.3,
        "failure_type": "hallucination",
        "failure_severity": "high",
        "latency_ms": 245,
    }
    event.update(overrides)
    return event
