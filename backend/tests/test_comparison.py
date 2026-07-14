"""ShadowComparison: shadow A/B model comparison in the SDK (no HTTP)."""

import pytest

from sdk.comparison import ShadowComparison


class FakeInvestigator:
    def __init__(self):
        self.events = []

    def report_failure(self, event):
        self.events.append(event)
        return True


@pytest.fixture
def fake():
    return FakeInvestigator()


def _comparison(fake, **kwargs):
    defaults = dict(
        investigator=fake,
        primary_model="model-a",
        candidate_model="model-b",
        task_type="rag_qa",
        sample_rate=1.0,
    )
    defaults.update(kwargs)
    return ShadowComparison(**defaults)


def test_both_models_reported_on_same_prompt(fake):
    comparison = _comparison(fake)
    result = comparison.run(
        "what is up?",
        primary_fn=lambda p: "the sky",
        candidate_fn=lambda p: "clouds",
    )

    assert result == "the sky"
    assert len(fake.events) == 2
    primary, candidate = fake.events
    assert primary["model_name"] == "model-a"
    assert candidate["model_name"] == "model-b"
    # Paired by session, tagged by experiment, no failure_type on success
    assert primary["session_id"] == candidate["session_id"]
    assert comparison.comparison_id in primary["tags"]
    assert "failure_type" not in primary
    assert "failure_type" not in candidate
    assert primary["task_type"] == "rag_qa"
    assert primary["prompt"] == candidate["prompt"] == "what is up?"


def test_candidate_exception_reported_but_not_raised(fake):
    def exploding(p):
        raise RuntimeError("connection timed out")

    result = _comparison(fake).run(
        "q", primary_fn=lambda p: "fine", candidate_fn=exploding
    )

    assert result == "fine"
    candidate = next(e for e in fake.events if e["model_name"] == "model-b")
    assert candidate["failure_type"] == "timeout"


def test_primary_exception_reported_and_reraised(fake):
    def exploding(p):
        raise RuntimeError("rate limit exceeded")

    with pytest.raises(RuntimeError):
        _comparison(fake).run("q", primary_fn=exploding, candidate_fn=lambda p: "ok")

    primary = next(e for e in fake.events if e["model_name"] == "model-a")
    assert primary["failure_type"] == "rate_limited"
    # The candidate still shadow-ran despite the primary failing
    assert any(e["model_name"] == "model-b" for e in fake.events)


def test_sample_rate_zero_never_shadows(fake):
    comparison = _comparison(fake, sample_rate=0.0)
    for _ in range(5):
        comparison.run("q", primary_fn=lambda p: "ok", candidate_fn=lambda p: "ok")

    assert all(e["model_name"] == "model-a" for e in fake.events)
    assert len(fake.events) == 5


def test_dict_results_carry_token_usage(fake):
    _comparison(fake).run(
        "q",
        primary_fn=lambda p: {"response": "ok", "input_tokens": 100, "output_tokens": 20},
        candidate_fn=lambda p: "ok",
    )
    primary = next(e for e in fake.events if e["model_name"] == "model-a")
    assert primary["input_tokens"] == 100
    assert primary["output_tokens"] == 20
    assert primary["response"] == "ok"


def test_default_classify_flags_empty_response(fake):
    _comparison(fake).run(
        "q", primary_fn=lambda p: "  ", candidate_fn=lambda p: "ok"
    )
    primary = next(e for e in fake.events if e["model_name"] == "model-a")
    assert primary["failure_type"] == "empty_response"


def test_custom_classifier(fake):
    def classify(text):
        return "malformed_response" if not text.startswith("{") else None

    _comparison(fake, classify=classify).run(
        "q", primary_fn=lambda p: "not json", candidate_fn=lambda p: '{"ok": 1}'
    )
    primary = next(e for e in fake.events if e["model_name"] == "model-a")
    candidate = next(e for e in fake.events if e["model_name"] == "model-b")
    assert primary["failure_type"] == "malformed_response"
    assert "failure_type" not in candidate
