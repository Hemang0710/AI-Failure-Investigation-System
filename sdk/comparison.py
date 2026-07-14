"""Shadow A/B comparison of two models on identical live prompts.

The strongest evidence that model X beats model Y on your workload is running
both on the *same* prompts. ``ShadowComparison`` wraps a live call path: the
primary model serves every request as usual, and a sampled fraction of
requests is additionally sent to a candidate model in shadow mode. Both
outcomes are reported as events (tagged with a shared comparison id and a
per-call session id), so the Model Fit dashboard page and the
``/recommendations`` endpoint compare the two models on identical traffic.

A candidate failure never affects the primary result - shadow calls are
best-effort and all their errors are swallowed into failure events.

Usage:
    from sdk import FailureInvestigator, ShadowComparison

    investigator = FailureInvestigator(api_key="sk-...")
    comparison = investigator.compare_models(
        primary_model="gpt-4o",
        candidate_model="claude-3-5-sonnet",
        task_type="rag_qa",
        sample_rate=0.1,        # shadow 1 in 10 requests
    )

    result = comparison.run(
        prompt,
        primary_fn=lambda p: openai_call(p),
        candidate_fn=lambda p: anthropic_call(p),
    )   # returns the primary model's response
"""

import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _default_classify(response_text: str) -> Optional[str]:
    """Minimal built-in check: only catches empty responses."""
    if not (response_text or "").strip():
        return "empty_response"
    return None


def _exception_failure_type(exc: Exception) -> str:
    message = str(exc).lower()
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if "rate" in message and "limit" in message:
        return "rate_limited"
    return "semantic_error"


def _unpack(result: Any) -> Tuple[str, Optional[int], Optional[int]]:
    """Accept either a plain response string or a dict with token usage."""
    if isinstance(result, dict):
        return (
            str(result.get("response", "")),
            result.get("input_tokens"),
            result.get("output_tokens"),
        )
    return str(result), None, None


class ShadowComparison:
    """Run a candidate model in shadow against the live primary model."""

    def __init__(
        self,
        investigator,
        primary_model: str,
        candidate_model: str,
        task_type: Optional[str] = None,
        sample_rate: float = 0.1,
        classify: Optional[Callable[[str], Optional[str]]] = None,
        comparison_id: Optional[str] = None,
        primary_provider: Optional[str] = None,
        candidate_provider: Optional[str] = None,
    ):
        """
        Args:
            investigator: FailureInvestigator used to report both outcomes
            primary_model / candidate_model: model names as reported in events
            task_type: task category attached to every event, so results land
                on the Model Fit page under the right task
            sample_rate: fraction of calls that also run the candidate (0-1]
            classify: optional callable(response_text) -> failure_type or
                None; defaults to flagging empty responses only. Supply your
                own to detect malformed JSON, hallucinations, etc.
            comparison_id: tag shared by all events of this experiment
                (default: generated cmp_xxx)
        """
        self.investigator = investigator
        self.primary_model = primary_model
        self.candidate_model = candidate_model
        self.task_type = task_type
        self.sample_rate = sample_rate
        self.classify = classify or _default_classify
        self.comparison_id = comparison_id or f"cmp_{uuid.uuid4().hex[:8]}"
        self.primary_provider = primary_provider
        self.candidate_provider = candidate_provider

    def _report(
        self,
        model: str,
        provider: Optional[str],
        role: str,
        prompt: str,
        session_id: str,
        response_text: str,
        failure_type: Optional[str],
        latency_ms: int,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
    ) -> None:
        event: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "model_name": model,
            "prompt": prompt,
            "response": response_text,
            "response_length": len(response_text),
            "latency_ms": latency_ms,
            "session_id": session_id,
            "tags": ["ab-test", self.comparison_id, role],
        }
        if provider:
            event["provider"] = provider
        if self.task_type:
            event["task_type"] = self.task_type
        if input_tokens is not None:
            event["input_tokens"] = input_tokens
        if output_tokens is not None:
            event["output_tokens"] = output_tokens
        if failure_type:
            event["failure_type"] = failure_type
            event["failure_severity"] = "medium"
        self.investigator.report_failure(event)

    def _call_and_report(
        self,
        model: str,
        provider: Optional[str],
        role: str,
        fn: Callable[[str], Any],
        prompt: str,
        session_id: str,
    ) -> Tuple[Any, Optional[Exception]]:
        start = time.monotonic()
        try:
            raw = fn(prompt)
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            self._report(
                model, provider, role, prompt, session_id,
                response_text="",
                failure_type=_exception_failure_type(exc),
                latency_ms=latency_ms,
                input_tokens=None, output_tokens=None,
            )
            return None, exc

        latency_ms = int((time.monotonic() - start) * 1000)
        text, input_tokens, output_tokens = _unpack(raw)
        try:
            failure_type = self.classify(text)
        except Exception as exc:
            logger.error(f"classify() raised; treating as success: {exc}")
            failure_type = None
        self._report(
            model, provider, role, prompt, session_id,
            response_text=text,
            failure_type=failure_type,
            latency_ms=latency_ms,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )
        return raw, None

    def run(
        self,
        prompt: str,
        primary_fn: Callable[[str], Any],
        candidate_fn: Callable[[str], Any],
    ) -> Any:
        """
        Serve a request with the primary model; maybe shadow the candidate.

        Returns the primary function's result unchanged; re-raises the
        primary function's exception after reporting it. Candidate errors
        are reported but never raised.

        Functions may return either a response string, or a dict like
        {"response": str, "input_tokens": int, "output_tokens": int} to
        enable cost comparison.
        """
        session_id = f"cmp-call-{uuid.uuid4().hex[:8]}"

        result, primary_exc = self._call_and_report(
            self.primary_model, self.primary_provider, "primary",
            primary_fn, prompt, session_id,
        )

        if random.random() < self.sample_rate:
            try:
                self._call_and_report(
                    self.candidate_model, self.candidate_provider, "candidate",
                    candidate_fn, prompt, session_id,
                )
            except Exception as exc:  # belt and braces: shadow must not break live traffic
                logger.error(f"Shadow candidate call failed unexpectedly: {exc}")

        if primary_exc is not None:
            raise primary_exc
        return result
