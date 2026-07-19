"""Tests for the drop-in auto-instrumentation (sdk.auto).

These exercise the logic that must be correct regardless of which provider SDK
is installed, so they use lightweight dummy client classes instead of real
``openai``/``anthropic`` packages. Network is never touched: a fake investigator
captures reported events.
"""

import threading
import time
import types

import pytest

from sdk import auto


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeInvestigator:
    """Captures report_success / report_failure calls (thread-safe)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.successes = []
        self.failures = []

    def report_success(self, **kwargs):
        with self._lock:
            self.successes.append(kwargs)
        return True

    def report_failure(self, event):
        with self._lock:
            self.failures.append(event)
        return True

    def flush(self):
        return True

    def close(self):
        return True

    # convenience
    @property
    def total(self):
        with self._lock:
            return len(self.successes) + len(self.failures)


def openai_response(text="ok", finish_reason="stop", model="gpt-4o", pt=100, ct=20):
    """Build an object shaped like an OpenAI chat.completions response."""
    message = types.SimpleNamespace(content=text)
    choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = types.SimpleNamespace(prompt_tokens=pt, completion_tokens=ct)
    return types.SimpleNamespace(model=model, choices=[choice], usage=usage)


class DummyCompletions:
    """Stand-in for openai.resources.chat.completions.Completions."""

    def __init__(self, response=None, exc=None):
        self._response = response if response is not None else openai_response()
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._response


@pytest.fixture(autouse=True)
def _clean_state():
    """Ensure every test starts and ends with instrumentation uninstalled."""
    auto.shutdown()
    yield
    auto.shutdown()


def _install_dummy(cls):
    """Patch a dummy class's create() with the sync wrapper, like _patch_openai."""
    auto._install(cls, "create", auto._wrap_sync, "openai", auto._extract_openai)


def _wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


# --------------------------------------------------------------------------- #
# Tier 0 — pure classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exc,expected",
    [
        (TimeoutError("request timed out"), "timeout"),
        (Exception("Rate limit reached for gpt-4o"), "rate_limited"),
        (Exception("This model's maximum context length is 8192 tokens"), "token_limit"),
        (Exception("something else entirely"), "semantic_error"),
    ],
)
def test_classify_exception(exc, expected):
    assert auto.classify_exception(exc) == expected


def test_classify_exception_status_429():
    err = Exception("too many requests")
    err.status_code = 429
    assert auto.classify_exception(err) == "rate_limited"


@pytest.mark.parametrize(
    "text,finish,expects_json,expected",
    [
        ("hello", "stop", False, None),
        ("", "stop", False, "empty_response"),
        ("   ", "stop", False, "empty_response"),
        ("partial", "length", False, "token_limit"),
        ('{"a": 1}', "stop", True, None),
        ('{"a": ', "stop", True, "malformed_response"),
        ("not json", "stop", True, "malformed_response"),
    ],
)
def test_content_failure(text, finish, expects_json, expected):
    assert auto._content_failure(text, finish, expects_json) == expected


def test_extract_openai():
    model, text, finish, pt, ct = auto._extract_openai(openai_response(text="hi", pt=5, ct=7), {})
    assert (model, text, finish, pt, ct) == ("gpt-4o", "hi", "stop", 5, 7)


# --------------------------------------------------------------------------- #
# Patch / unpatch lifecycle
# --------------------------------------------------------------------------- #
def test_install_and_shutdown_restores_original():
    original = DummyCompletions.create
    auto.init(investigator=FakeInvestigator(), providers=[])
    _install_dummy(DummyCompletions)
    assert DummyCompletions.create is not original
    assert getattr(DummyCompletions.create, "_fi_wrapped", False) is True

    auto.shutdown()
    assert DummyCompletions.create is original


def test_double_init_is_noop():
    fake = FakeInvestigator()
    auto.init(investigator=fake, providers=[])
    auto.init(investigator=FakeInvestigator(), providers=[])  # ignored
    # first investigator still the active one
    assert auto._state.investigator is fake


def test_init_missing_provider_library_does_not_crash():
    # 'openai' almost certainly isn't installed in CI; init must skip it cleanly.
    auto.init(investigator=FakeInvestigator(), providers=["openai", "anthropic"])
    assert auto.is_active() in (True, False)  # no exception is the point


# --------------------------------------------------------------------------- #
# Success / failure capture through the wrapper
# --------------------------------------------------------------------------- #
def test_successful_call_reports_success_with_tokens():
    fake = FakeInvestigator()
    auto.init(investigator=fake, providers=[], default_task_type="chat")
    _install_dummy(DummyCompletions)

    result = DummyCompletions().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])

    assert result is not None
    assert len(fake.successes) == 1
    ev = fake.successes[0]
    assert ev["model_name"] == "gpt-4o"
    assert ev["provider"] == "openai"
    assert ev["task_type"] == "chat"
    assert ev["input_tokens"] == 100
    assert ev["output_tokens"] == 20
    assert "auto" in ev["tags"]


def test_empty_response_reports_failure():
    fake = FakeInvestigator()
    auto.init(investigator=fake, providers=[])
    _install_dummy(DummyCompletions)

    DummyCompletions(response=openai_response(text="")).create(model="gpt-4o")

    assert len(fake.failures) == 1
    assert fake.failures[0]["failure_type"] == "empty_response"
    assert len(fake.successes) == 0


def test_exception_reports_failure_and_reraises():
    fake = FakeInvestigator()
    auto.init(investigator=fake, providers=[])
    _install_dummy(DummyCompletions)

    with pytest.raises(TimeoutError):
        DummyCompletions(exc=TimeoutError("timed out")).create(model="gpt-4o")

    assert len(fake.failures) == 1
    assert fake.failures[0]["failure_type"] == "timeout"
    assert fake.failures[0]["failure_severity"] == "high"


def test_redaction_default_omits_body():
    fake = FakeInvestigator()
    auto.init(investigator=fake, providers=[])  # redact_content defaults True
    _install_dummy(DummyCompletions)

    DummyCompletions(response=openai_response(text="")).create(model="gpt-4o")
    assert fake.failures[0]["response"] == ""


def test_instrumentation_never_breaks_caller():
    class ExplodingInvestigator(FakeInvestigator):
        def report_success(self, **kwargs):
            raise RuntimeError("backend down")

    auto.init(investigator=ExplodingInvestigator(), providers=[])
    _install_dummy(DummyCompletions)

    # The reporting error must be swallowed; the model response still returns.
    result = DummyCompletions().create(model="gpt-4o")
    assert result is not None


def test_success_sampling_zero_records_nothing():
    fake = FakeInvestigator()
    auto.init(investigator=fake, providers=[], sample_rate=0.0)
    _install_dummy(DummyCompletions)

    DummyCompletions().create(model="gpt-4o")
    assert fake.total == 0  # sampled out


# --------------------------------------------------------------------------- #
# Tier 2 — judge worker
# --------------------------------------------------------------------------- #
def test_judge_flags_failure_once_no_double_count():
    fake = FakeInvestigator()

    def judge_fn(prompt, response, task):
        return {"failure_type": "hallucination", "confidence": 0.9}

    auto.init(investigator=fake, providers=[], judge=judge_fn, judge_sample=1.0)
    _install_dummy(DummyCompletions)

    DummyCompletions(response=openai_response(text="Paris is the capital of Brazil")).create(
        model="gpt-4o", messages=[{"role": "user", "content": "capital of Brazil?"}]
    )

    assert _wait_until(lambda: fake.total >= 1)
    time.sleep(0.1)  # allow any erroneous second event to surface
    # Exactly one event, and it's the judged failure - not a success + failure.
    assert fake.total == 1
    assert len(fake.failures) == 1
    assert fake.failures[0]["failure_type"] == "hallucination"
    assert "judged" in fake.failures[0]["tags"]
    assert fake.failures[0]["confidence_score"] == 0.9


def test_judge_pass_reports_single_success():
    fake = FakeInvestigator()

    def judge_fn(prompt, response, task):
        return {"failure_type": None}

    auto.init(investigator=fake, providers=[], judge=judge_fn, judge_sample=1.0)
    _install_dummy(DummyCompletions)

    DummyCompletions().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])

    assert _wait_until(lambda: fake.total >= 1)
    time.sleep(0.1)
    assert fake.total == 1
    assert len(fake.successes) == 1
