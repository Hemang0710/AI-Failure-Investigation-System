"""Drop-in auto-instrumentation for LLM calls.

The goal is a **two-line** integration: call :func:`init` once at process start
and every OpenAI / Anthropic / LangChain call is captured automatically - real
model name, token counts, latency, cost (estimated server-side from tokens) and
success/failure - with *zero* changes at call sites.

    from sdk import auto
    auto.init(api_key="sk-...")          # or set FAILURE_INVESTIGATOR_API_KEY

    # existing code, unchanged:
    resp = openai_client.chat.completions.create(model="gpt-4o", messages=[...])

What it captures
----------------
* **Tier 0 (free, automatic):** every call becomes a success or a failure.
  Operational failures are detected without any judgement call:

  =====================================  ====================
  condition                              failure_type
  =====================================  ====================
  request raised a timeout               ``timeout``
  request was rate limited (HTTP 429)    ``rate_limited``
  context/length error / truncation      ``token_limit``
  any other exception                    ``semantic_error``
  empty / whitespace output              ``empty_response``
  JSON was requested but didn't parse    ``malformed_response``
  =====================================  ====================

* **Tier 2 (opt-in, costs tokens):** pass ``judge="gpt-4o-mini"`` and a sampled
  fraction of *successful* responses are graded by a cheap model for
  hallucination / semantic quality on a background thread. Judged events are
  tagged ``judged`` and carry the judge's confidence, so they stay visually
  distinct from ground truth. Judging never blocks the caller and, to avoid
  double-counting, a call selected for judging is reported exactly once (by the
  judge worker) rather than twice.

Honesty boundary
----------------
Tier 0 captures *operational* truth only; it never guesses hallucination. Real
quality signal requires the opt-in judge (an estimate, clearly tagged) or your
own product feedback. Nothing here pretends otherwise.

Safety guarantees
-----------------
* Non-blocking: reporting goes through the SDK's background batcher.
* Never breaks the caller: instrumentation errors are logged and dropped; the
  user's real exception always propagates unchanged.
* Idempotent: re-calling :func:`init` is a no-op; :func:`shutdown` restores the
  original methods (used by tests and clean exits).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence

from .client import FailureInvestigator

logger = logging.getLogger(__name__)

# Failure types the judge is allowed to assign. It must never invent an
# operational failure (timeout, rate_limited, ...) - those are Tier 0's job.
JUDGE_FAILURE_TYPES = {"hallucination", "semantic_error", "confidence_mismatch"}

_JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of an AI assistant's response. Decide whether "
    "the response is a failure. Only flag clear problems. Reply with a compact "
    'JSON object: {"failure_type": <one of "hallucination", "semantic_error", '
    '"confidence_mismatch", or null>, "confidence": <0.0-1.0>}. Use '
    '"hallucination" for fabricated or factually wrong content, "semantic_error" '
    'for off-topic or logically broken answers, "confidence_mismatch" for '
    "confidently-stated wrong answers, and null when the response is acceptable."
)


# --------------------------------------------------------------------------- #
# Configuration & module state
# --------------------------------------------------------------------------- #
@dataclass
class _Config:
    environment: str = "production"
    default_task_type: Optional[str] = None
    task_type_fn: Optional[Callable[[dict], Optional[str]]] = None
    sample_rate: float = 1.0
    redact_content: bool = True
    judge_sample: float = 0.05
    judge_tasks: Optional[set] = None


@dataclass
class _State:
    investigator: Optional[FailureInvestigator] = None
    config: _Config = field(default_factory=_Config)
    installed: list = field(default_factory=list)  # (owner, attr, original)
    judge: Optional["_JudgeWorker"] = None
    # Thread-local flag: while set, wrapped calls skip instrumentation. Used so
    # the judge's own LLM calls don't recursively report themselves.
    suppress: threading.local = field(default_factory=threading.local)
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = _State()


def _suppressed() -> bool:
    return getattr(_state.suppress, "on", False)


@contextlib.contextmanager
def _suppress_instrumentation():
    prev = getattr(_state.suppress, "on", False)
    _state.suppress.on = True
    try:
        yield
    finally:
        _state.suppress.on = prev


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def init(
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    providers: Sequence[str] = ("openai", "anthropic", "langchain"),
    environment: Optional[str] = None,
    default_task_type: Optional[str] = None,
    task_type: Optional[Callable[[dict], Optional[str]]] = None,
    sample_rate: Optional[float] = None,
    redact_content: Optional[bool] = None,
    judge: Optional[Any] = None,
    judge_sample: Optional[float] = None,
    judge_tasks: Optional[Sequence[str]] = None,
    investigator: Optional[FailureInvestigator] = None,
) -> None:
    """Install auto-instrumentation. Safe to call once at process start.

    Args:
        api_key: API key for the backend (falls back to
            ``FAILURE_INVESTIGATOR_API_KEY``). Ignored if ``investigator`` given.
        endpoint: Backend URL (falls back to ``FAILURE_INVESTIGATOR_ENDPOINT``
            or ``http://localhost:8000``).
        providers: Which client libraries to patch. Any of ``"openai"``,
            ``"anthropic"``, ``"langchain"``. Missing libraries are skipped.
        environment: Value stored on every event (default ``"production"`` or
            ``FI_AUTO_ENVIRONMENT``).
        default_task_type: Task type attached when ``task_type`` isn't given.
        task_type: ``callable(create_kwargs) -> task_type|None`` to infer the
            task per call (wins over ``default_task_type``).
        sample_rate: Fraction of *successful* calls to record (0-1]. Failures
            are always recorded. Default 1.0.
        redact_content: When True (default) prompt/response bodies are never
            sent to the backend - only metadata. The judge still sees them
            locally, before anything leaves the process.
        judge: Enable the LLM judge. Either a model name string (e.g.
            ``"gpt-4o-mini"``, uses the built-in OpenAI judge) or a callable
            ``(prompt, response, task_type) -> {"failure_type", "confidence"}``.
        judge_sample: Fraction of recorded successes to judge (default 0.05).
        judge_tasks: Restrict judging to these task types (default: all).
        investigator: Supply a pre-built client (mainly for tests).

    Environment fallbacks mirror the args: ``FI_AUTO_ENVIRONMENT``,
    ``FI_AUTO_SAMPLE_RATE``, ``FI_AUTO_DEFAULT_TASK_TYPE``, ``FI_AUTO_JUDGE``,
    ``FI_AUTO_JUDGE_SAMPLE``, ``FI_AUTO_REDACT_CONTENT``.
    """
    with _state.lock:
        if _state.investigator is not None:
            logger.info("auto.init() already active; ignoring repeat call")
            return

        _state.investigator = investigator or _build_investigator(api_key, endpoint)

        cfg = _Config()
        cfg.environment = environment or os.getenv("FI_AUTO_ENVIRONMENT", "production")
        cfg.default_task_type = default_task_type or os.getenv("FI_AUTO_DEFAULT_TASK_TYPE") or None
        cfg.task_type_fn = task_type
        cfg.sample_rate = _as_float(sample_rate, "FI_AUTO_SAMPLE_RATE", 1.0)
        cfg.redact_content = _as_bool(redact_content, "FI_AUTO_REDACT_CONTENT", True)
        cfg.judge_sample = _as_float(judge_sample, "FI_AUTO_JUDGE_SAMPLE", 0.05)
        cfg.judge_tasks = set(judge_tasks) if judge_tasks else None
        _state.config = cfg

        judge_spec = judge if judge is not None else (os.getenv("FI_AUTO_JUDGE") or None)
        if judge_spec:
            _state.judge = _JudgeWorker(_resolve_judge_fn(judge_spec))
            _state.judge.start()

        for name in providers:
            try:
                _PATCHERS[name]()
            except KeyError:
                logger.warning("auto.init: unknown provider %r, skipping", name)
            except Exception as exc:  # a missing/renamed library must not crash init
                logger.info("auto.init: provider %r not instrumented (%s)", name, exc)

        logger.info(
            "auto-instrumentation active: providers=%s judge=%s",
            [o.__module__ for o, _, _ in _state.installed] or "none",
            bool(_state.judge),
        )


def shutdown() -> None:
    """Restore original methods, stop the judge, and flush buffered events."""
    with _state.lock:
        for owner, attr, original in reversed(_state.installed):
            with contextlib.suppress(Exception):
                setattr(owner, attr, original)
        _state.installed.clear()

        if _state.judge is not None:
            _state.judge.stop()
            _state.judge = None

        if _state.investigator is not None:
            with contextlib.suppress(Exception):
                _state.investigator.close()
            _state.investigator = None


def flush() -> None:
    """Force-send any buffered events."""
    if _state.investigator is not None:
        _state.investigator.flush()


def is_active() -> bool:
    return bool(_state.installed)


# --------------------------------------------------------------------------- #
# Tier 0 detection
# --------------------------------------------------------------------------- #
def classify_exception(exc: BaseException) -> str:
    """Map a provider exception to a failure_type (best-effort, name+message)."""
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)

    if "timeout" in name or "timeout" in message or "timed out" in message:
        return "timeout"
    if status == 429 or "ratelimit" in name or ("rate" in message and "limit" in message):
        return "rate_limited"
    if (
        "context" in message and ("length" in message or "window" in message)
    ) or "maximum context" in message or "max_tokens" in message or "too many tokens" in message:
        return "token_limit"
    return "semantic_error"


def _content_failure(text: Optional[str], finish_reason: Optional[str], expects_json: bool) -> Optional[str]:
    """Failure type for a *successful* HTTP response, or None if it looks fine."""
    if not (text or "").strip():
        return "empty_response"
    reason = (finish_reason or "").lower()
    if reason in ("length", "max_tokens"):
        return "token_limit"
    if expects_json and not _parses_as_json(text):
        return "malformed_response"
    return None


def _parses_as_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Reporting core
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _task_for(kwargs: dict) -> Optional[str]:
    cfg = _state.config
    if cfg.task_type_fn is not None:
        with contextlib.suppress(Exception):
            inferred = cfg.task_type_fn(kwargs)
            if inferred:
                return inferred
    return cfg.default_task_type


def _handle_success(
    provider: str,
    model: str,
    kwargs: dict,
    text: Optional[str],
    finish_reason: Optional[str],
    latency_ms: int,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> None:
    """Classify a returned response and report it (success or Tier 0 failure)."""
    cfg = _state.config
    task = _task_for(kwargs)
    expects_json = _expects_json(kwargs)

    failure_type = _content_failure(text, finish_reason, expects_json)
    if failure_type is not None:
        _report_failure(
            provider, model, task, failure_type, "medium",
            latency_ms, input_tokens, output_tokens,
            response_text=text, tags=["auto"],
        )
        return

    # Success. Apply success sampling here (failures are never sampled out).
    if cfg.sample_rate < 1.0 and random.random() >= cfg.sample_rate:
        return

    # Route a sampled slice to the judge, which will report the final verdict
    # (success or failure) exactly once - avoiding a success+failure double count.
    if _state.judge is not None and _should_judge(task):
        _state.judge.submit(
            {
                "provider": provider, "model": model, "task": task,
                "latency_ms": latency_ms,
                "input_tokens": input_tokens, "output_tokens": output_tokens,
                "prompt": _prompt_text(kwargs), "response": text or "",
            }
        )
        return

    _report_success(provider, model, task, latency_ms, input_tokens, output_tokens)


def _handle_exception(provider: str, model: str, kwargs: dict, exc: BaseException, latency_ms: int) -> None:
    _report_failure(
        provider, model, _task_for(kwargs), classify_exception(exc), "high",
        latency_ms, None, None, response_text="", tags=["auto"],
    )


def _report_success(
    provider: str, model: str, task: Optional[str],
    latency_ms: int, input_tokens: Optional[int], output_tokens: Optional[int],
) -> None:
    inv = _state.investigator
    if inv is None:
        return
    with contextlib.suppress(Exception):
        inv.report_success(
            model_name=model,
            task_type=task,
            provider=provider,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            environment=_state.config.environment,
            tags=["auto"],
        )


def _report_failure(
    provider: str, model: str, task: Optional[str],
    failure_type: str, severity: str,
    latency_ms: Optional[int], input_tokens: Optional[int], output_tokens: Optional[int],
    response_text: Optional[str] = "", tags: Optional[list] = None,
    confidence_score: Optional[float] = None,
) -> None:
    inv = _state.investigator
    if inv is None:
        return
    keep_body = not _state.config.redact_content
    event: dict = {
        "timestamp": _now_iso(),
        "model_name": model,
        "provider": provider,
        "prompt": "",
        "response": (response_text or "") if keep_body else "",
        "failure_type": failure_type,
        "failure_severity": severity,
        "environment": _state.config.environment,
        "tags": tags or ["auto"],
    }
    if task:
        event["task_type"] = task
    if latency_ms is not None:
        event["latency_ms"] = latency_ms
    if input_tokens is not None:
        event["input_tokens"] = input_tokens
    if output_tokens is not None:
        event["output_tokens"] = output_tokens
    if confidence_score is not None:
        event["confidence_score"] = round(float(confidence_score), 3)
    with contextlib.suppress(Exception):
        inv.report_failure(event)


def _expects_json(kwargs: dict) -> bool:
    fmt = kwargs.get("response_format")
    if isinstance(fmt, dict) and fmt.get("type") in ("json_object", "json_schema"):
        return True
    if fmt in ("json", "json_object"):
        return True
    return False


def _prompt_text(kwargs: dict) -> str:
    """Best-effort flatten of the request messages for the judge (local only)."""
    messages = kwargs.get("messages")
    if isinstance(messages, list):
        parts = []
        for m in messages:
            if isinstance(m, dict):
                content = m.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):  # anthropic-style blocks
                    parts.extend(
                        b.get("text", "") for b in content if isinstance(b, dict)
                    )
        return "\n".join(p for p in parts if p)
    return str(kwargs.get("prompt", ""))


def _should_judge(task: Optional[str]) -> bool:
    cfg = _state.config
    if cfg.judge_tasks is not None and task not in cfg.judge_tasks:
        return False
    return random.random() < cfg.judge_sample


# --------------------------------------------------------------------------- #
# Response extractors
# --------------------------------------------------------------------------- #
def _extract_openai(resp: Any, kwargs: dict):
    model = getattr(resp, "model", None) or kwargs.get("model", "unknown")
    text, finish_reason = None, None
    choices = getattr(resp, "choices", None)
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        text = getattr(message, "content", None) if message is not None else None
        finish_reason = getattr(first, "finish_reason", None)
    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", None) if usage else None
    out_tok = getattr(usage, "completion_tokens", None) if usage else None
    return model, text, finish_reason, in_tok, out_tok


def _extract_anthropic(resp: Any, kwargs: dict):
    model = getattr(resp, "model", None) or kwargs.get("model", "unknown")
    blocks = getattr(resp, "content", None) or []
    text = "".join(
        getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text"
    )
    finish_reason = getattr(resp, "stop_reason", None)
    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "input_tokens", None) if usage else None
    out_tok = getattr(usage, "output_tokens", None) if usage else None
    return model, text, finish_reason, in_tok, out_tok


# --------------------------------------------------------------------------- #
# Provider adapters (monkeypatch create-methods)
# --------------------------------------------------------------------------- #
def _wrap_sync(original, provider: str, extract):
    def wrapper(self, *args, **kwargs):
        if _suppressed():
            return original(self, *args, **kwargs)
        start = time.monotonic()
        try:
            resp = original(self, *args, **kwargs)
        except BaseException as exc:
            latency = int((time.monotonic() - start) * 1000)
            _safely(_handle_exception, provider, kwargs.get("model", "unknown"), kwargs, exc, latency)
            raise
        latency = int((time.monotonic() - start) * 1000)
        _safely(_dispatch_success, provider, extract, resp, kwargs, latency)
        return resp

    wrapper._fi_wrapped = True
    return wrapper


def _wrap_async(original, provider: str, extract):
    async def wrapper(self, *args, **kwargs):
        if _suppressed():
            return await original(self, *args, **kwargs)
        start = time.monotonic()
        try:
            resp = await original(self, *args, **kwargs)
        except BaseException as exc:
            latency = int((time.monotonic() - start) * 1000)
            _safely(_handle_exception, provider, kwargs.get("model", "unknown"), kwargs, exc, latency)
            raise
        latency = int((time.monotonic() - start) * 1000)
        _safely(_dispatch_success, provider, extract, resp, kwargs, latency)
        return resp

    wrapper._fi_wrapped = True
    return wrapper


def _dispatch_success(provider, extract, resp, kwargs, latency):
    model, text, finish_reason, in_tok, out_tok = extract(resp, kwargs)
    _handle_success(provider, model, kwargs, text, finish_reason, latency, in_tok, out_tok)


def _safely(fn, *args) -> None:
    """Run instrumentation without ever propagating its own errors."""
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 - instrumentation must never break callers
        logger.debug("auto-instrumentation error (ignored): %s", exc)


def _install(owner, attr, wrapper_factory, provider, extract) -> None:
    original = getattr(owner, attr)
    if getattr(original, "_fi_wrapped", False):
        return  # already patched
    wrapper = wrapper_factory(original, provider, extract)
    setattr(owner, attr, wrapper)
    _state.installed.append((owner, attr, original))


def _patch_openai() -> None:
    from openai.resources.chat.completions import Completions, AsyncCompletions

    _install(Completions, "create", _wrap_sync, "openai", _extract_openai)
    _install(AsyncCompletions, "create", _wrap_async, "openai", _extract_openai)


def _patch_anthropic() -> None:
    from anthropic.resources.messages import Messages, AsyncMessages

    _install(Messages, "create", _wrap_sync, "anthropic", _extract_anthropic)
    _install(AsyncMessages, "create", _wrap_async, "anthropic", _extract_anthropic)


def _patch_langchain() -> None:
    handler = build_langchain_handler()
    # Best-effort global registration so existing chains need no edits.
    registered = False
    with contextlib.suppress(Exception):
        from langchain_core.callbacks.manager import get_callback_manager  # type: ignore

        get_callback_manager().add_handler(handler, inherit=True)
        registered = True
    if not registered:
        logger.info(
            "auto: LangChain detected. Global auto-registration is unavailable on "
            "this version; pass callbacks=[auto.build_langchain_handler()] to your "
            "chain/LLM to capture events."
        )


def build_langchain_handler():
    """Return a LangChain callback handler that reports events to the backend.

    Works with either ``langchain_core`` or legacy ``langchain`` installs. Pass
    it via ``config={"callbacks": [handler]}`` if global registration isn't
    available on your version.
    """
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except Exception:  # pragma: no cover - legacy fallback
        from langchain.callbacks.base import BaseCallbackHandler  # type: ignore

    class FailureInvestigatorCallbackHandler(BaseCallbackHandler):
        def __init__(self):
            self._starts: dict = {}

        def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs):
            self._starts[run_id] = time.monotonic()

        def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs):
            self._starts[run_id] = time.monotonic()

        def on_llm_end(self, response, *, run_id=None, **kwargs):
            start = self._starts.pop(run_id, None)
            latency = int((time.monotonic() - start) * 1000) if start else None
            _safely(_handle_langchain_end, response, latency)

        def on_llm_error(self, error, *, run_id=None, **kwargs):
            start = self._starts.pop(run_id, None)
            latency = int((time.monotonic() - start) * 1000) if start else 0
            model = "unknown"
            _safely(_report_failure, "langchain", model, _state.config.default_task_type,
                    classify_exception(error), "high", latency, None, None, "", ["auto"])

    return FailureInvestigatorCallbackHandler()


def _handle_langchain_end(response, latency):
    output = getattr(response, "llm_output", None) or {}
    model = output.get("model_name") or output.get("model") or "unknown"
    usage = output.get("token_usage") or output.get("usage") or {}
    in_tok = usage.get("prompt_tokens") or usage.get("input_tokens")
    out_tok = usage.get("completion_tokens") or usage.get("output_tokens")
    text = _langchain_text(response)
    _handle_success("langchain", model, {}, text, None, latency or 0, in_tok, out_tok)


def _langchain_text(response) -> str:
    with contextlib.suppress(Exception):
        gens = getattr(response, "generations", None) or []
        return "".join(getattr(g, "text", "") or "" for row in gens for g in row)
    return ""


_PATCHERS = {
    "openai": _patch_openai,
    "anthropic": _patch_anthropic,
    "langchain": _patch_langchain,
}


# --------------------------------------------------------------------------- #
# Tier 2: LLM judge (opt-in, background)
# --------------------------------------------------------------------------- #
class _JudgeWorker:
    """Grades sampled successful responses on a daemon thread."""

    def __init__(self, judge_fn: Callable[[str, str, Optional[str]], dict], max_queue: int = 1000):
        self._judge_fn = judge_fn
        self._queue: "queue.Queue" = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._loop, name="fi-judge", daemon=True)
        self._stop = threading.Event()

    def start(self) -> None:
        self._thread.start()

    def submit(self, item: dict) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # Under load, drop the sample and just report the success rather
            # than block the caller or grow memory unbounded.
            _report_success(
                item["provider"], item["model"], item["task"],
                item["latency_ms"], item["input_tokens"], item["output_tokens"],
            )

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        with contextlib.suppress(Exception):
            self._queue.put_nowait(None)  # wake the loop
        self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            self._grade(item)

    def _grade(self, item: dict) -> None:
        verdict = {}
        try:
            with _suppress_instrumentation():  # judge's own LLM call isn't reported
                verdict = self._judge_fn(item["prompt"], item["response"], item["task"]) or {}
        except Exception as exc:  # judging must never lose the event
            logger.debug("judge failed, reporting as success: %s", exc)

        failure_type = verdict.get("failure_type")
        if failure_type in JUDGE_FAILURE_TYPES:
            _report_failure(
                item["provider"], item["model"], item["task"],
                failure_type, "medium",
                item["latency_ms"], item["input_tokens"], item["output_tokens"],
                response_text=item["response"], tags=["auto", "judged"],
                confidence_score=verdict.get("confidence"),
            )
        else:
            _report_success(
                item["provider"], item["model"], item["task"],
                item["latency_ms"], item["input_tokens"], item["output_tokens"],
            )


def _resolve_judge_fn(judge: Any) -> Callable[[str, str, Optional[str]], dict]:
    if callable(judge):
        return judge
    if isinstance(judge, str):
        return _make_openai_judge(judge)
    raise ValueError("judge must be a model-name string or a callable")


def _make_openai_judge(model: str) -> Callable[[str, str, Optional[str]], dict]:
    """Built-in judge that grades with a cheap OpenAI model."""
    def judge(prompt: str, response: str, task: Optional[str]) -> dict:
        from openai import OpenAI  # imported lazily; only needed when judging

        client = OpenAI()
        user = (
            f"TASK TYPE: {task or 'unknown'}\n\n"
            f"PROMPT:\n{prompt[:6000]}\n\nRESPONSE:\n{response[:6000]}\n\n"
            "Return only the JSON object."
        )
        completion = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        )
        return json.loads(completion.choices[0].message.content)

    return judge


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _build_investigator(api_key: Optional[str], endpoint: Optional[str]) -> FailureInvestigator:
    api_key = api_key or os.getenv("FAILURE_INVESTIGATOR_API_KEY")
    if not api_key:
        raise ValueError(
            "No API key. Pass api_key= or set FAILURE_INVESTIGATOR_API_KEY."
        )
    endpoint = endpoint or os.getenv("FAILURE_INVESTIGATOR_ENDPOINT", "http://localhost:8000")
    return FailureInvestigator(api_key=api_key, endpoint=endpoint)


def _as_float(value: Optional[float], env: str, default: float) -> float:
    if value is not None:
        return float(value)
    raw = os.getenv(env)
    if raw is not None:
        with contextlib.suppress(ValueError):
            return float(raw)
    return default


def _as_bool(value: Optional[bool], env: str, default: bool) -> bool:
    if value is not None:
        return bool(value)
    raw = os.getenv(env)
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return default
