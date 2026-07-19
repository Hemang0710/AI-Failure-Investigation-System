# Auto-Instrumentation Design — `failure_investigator.auto`

**Status:** Proposed (design only — no code written yet)
**Author:** drafted for Hemang Patel
**Goal:** Turn adoption from "hand-write reporting at every call site" into **two lines at startup**, so any real app captures real LLM telemetry automatically.

---

## 1. Problem & goal

Today a developer must call `report_success()` / `report_failure()` by hand at every
LLM call site (see `examples/openai_example.py`) **and** decide what a failure is
(the `classify()` function in `examples/ab_comparison_example.py`). That is too much
friction for a product people adopt casually.

**Target developer experience:**

```python
from failure_investigator import auto
auto.init(api_key="sk-...")          # or set FAILURE_INVESTIGATOR_API_KEY

# existing code, UNCHANGED:
resp = openai_client.chat.completions.create(model="gpt-4o", messages=[...])
```

After `auto.init()`, every OpenAI / Anthropic / LangChain call is captured with **real**
model name, token counts, latency, cost (estimated server-side from tokens), and
success/failure — with **zero changes at call sites**.

### Non-goals / honesty boundary
- Auto-instrumentation captures **operational** truth (what happened, how long, how much).
- It **cannot** decide semantic quality (hallucination, "the answer was wrong") on its own.
  That requires a human signal or an LLM judge. This design makes both **opt-in**, and
  never pretends Tier 0 detects hallucinations.

---

## 2. Scope (this iteration)

| Provider | Mechanism | Priority |
|---|---|---|
| **OpenAI** (`openai` v1.x) | Monkeypatch `chat.completions.create` (+ `responses.create`, sync & async) | P0 |
| **Anthropic** (`anthropic` ≥0.25) | Monkeypatch `messages.create` (sync & async) | P0 |
| **LangChain** | `BaseCallbackHandler` auto-attached via `langchain.callbacks` | P1 |

All three funnel into the **existing** `FailureInvestigator` client and `POST /api/v1/events`.
**No backend schema change is required for Tier 0.** The LLM judge (Tier 2) is a client-side
add-on and also needs no new endpoint.

---

## 3. Public API surface

```python
auto.init(
    api_key: str | None = None,          # falls back to env var
    endpoint: str | None = None,         # falls back to env var / localhost
    providers = ("openai", "anthropic", "langchain"),  # what to patch
    environment: str = "production",
    default_task_type: str | None = None,
    task_type: Callable[[dict], str] | None = None,   # infer per-call from kwargs
    sample_rate: float = 1.0,            # fraction of *successes* recorded (failures always 100%)
    judge: str | None = None,            # e.g. "gpt-4o-mini"; None = judge disabled
    judge_sample: float = 0.05,          # fraction of successful responses graded
    judge_tasks: set[str] | None = None, # restrict judging to some task types
    redact_content: bool = True,         # don't send prompt/response bodies at all if True
) -> None

auto.on_feedback(event_id: str, is_failure: bool,
                 failure_type: str | None = None) -> None   # wire to thumbs-down/retry

auto.flush()      # force-send buffered events
auto.shutdown()   # unpatch + flush + close (for tests / clean exit)
auto.last_event_id() -> str | None   # id of the most recent call on this thread
```

`init()` is **idempotent** and safe to call once at process start. It stores a module-level
`FailureInvestigator` and installs the requested patches.

---

## 4. Architecture

### 4.1 The wrapper pattern (per provider)

Each provider adapter replaces the SDK's create-method with a wrapper that:

1. starts a monotonic timer,
2. calls the original method,
3. on **exception** → classify (Tier 0) → `report_failure` → **re-raise** (never swallow),
4. on **success** → read `response.usage` + `response.model`, run content checks (Tier 0),
   optionally enqueue for the judge (Tier 2), then `report_success` **or** `report_failure`,
5. return the untouched response object.

Sketch (OpenAI, sync):

```python
def _wrap_openai():
    from openai.resources.chat import completions as C
    original = C.Completions.create

    @functools.wraps(original)
    def wrapped(self, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            resp = original(self, *args, **kwargs)
        except Exception as e:
            _safe_report_failure(kwargs, _classify_exception(e), t0)
            raise                                   # user's error is never hidden
        _handle_success(resp, kwargs, t0)           # swallows *its own* errors only
        return resp

    C.Completions.create = wrapped
    _installed.append((C.Completions, "create", original))   # for shutdown()
```

`async` variants patch `AsyncCompletions.create` with an `async def` wrapper.

### 4.2 Safety guarantees (product-grade)

- **Non-blocking:** reporting goes through the existing background-thread batcher in
  `sdk/client.py`; the hot path only appends to a buffer.
- **Never breaks the caller:** `_handle_success` and `_safe_report_failure` wrap all their
  own logic in `try/except` and log-and-drop on error. The user's real exception always
  propagates unchanged.
- **Idempotent patching:** re-`init()` detects existing patches and no-ops; `shutdown()`
  restores originals (critical for a clean test suite).
- **Fail-open:** if the backend is down, the SDK's retry/flush already degrades gracefully;
  the app keeps running.

---

## 5. Tier 0 — automatic detection (free, default)

### 5.1 Exception → failure type

| Condition (provider-agnostic, matched on exception type/message) | `failure_type` | severity |
|---|---|---|
| Timeout / `APITimeoutError` / "timed out" | `timeout` | high |
| Rate limit / HTTP 429 / `RateLimitError` | `rate_limited` | high |
| Context/output length / "maximum context length" / "max_tokens" | `token_limit` | high |
| Any other exception | `semantic_error` *(generic)* | high |

### 5.2 Successful-response content checks

| Condition | `failure_type` |
|---|---|
| Output text is empty/whitespace | `empty_response` |
| Caller passed a JSON response format (`response_format={"type":"json_object"}` or tool/`json` hint) **and** body doesn't parse | `malformed_response` |
| `finish_reason == "length"` (truncated) | `token_limit` |
| otherwise | *success* (no failure_type) |

Everything else is reported as a **success** with real tokens/latency/cost. This is the
honest core: Tier 0 never guesses hallucination.

### 5.3 Fields captured per event

`model_name` (from `resp.model`), `provider`, `latency_ms`, `input_tokens`,
`output_tokens` (→ backend estimates `cost_usd`), `environment`, `task_type`
(from `default_task_type`/`task_type()` callable, else null), `tags=["auto"]`.
Prompt/response bodies are **omitted by default** (`redact_content=True`) so the tool is
safe to switch on in production without shipping user content; PII redaction on the backend
remains a second line of defense when bodies are sent.

---

## 6. Tier 1 — feedback hook (one line)

The cheapest source of **real** hallucination/quality data is the user's own product signals.

```python
eid = auto.last_event_id()             # captured automatically per call
# ... user clicks 👎 / retries / edits the answer ...
auto.on_feedback(eid, is_failure=True, failure_type="hallucination")
```

Internally this posts to the existing `POST /api/v1/feedback` (already implemented) and/or
re-reports the event with a `failure_type`. Recommended integration points for adopters:
thumbs-down buttons, "regenerate" clicks, silent retries, and answer edits.

---

## 7. Tier 2 — LLM judge (opt-in, costs tokens)

Enabled only when `judge=` is set. **Off by default** because it spends money.

### 7.1 How it works
- After a successful call, with probability `judge_sample` (default 5%), the response is
  queued to a background judge worker (separate thread; never blocks the app).
- The judge calls a **cheap** model (e.g. `gpt-4o-mini`) with a strict rubric prompt over the
  `(prompt, response, optional retrieved_context)` and returns a small JSON verdict:
  `{"failure_type": null | "hallucination" | "semantic_error" | "confidence_mismatch", "confidence": 0-1}`.
- If it flags a failure, the original event is re-reported with that `failure_type` and
  `tags += ["judged"]`, plus the judge's confidence.

### 7.2 Cost control & correctness
- **Sampling** keeps cost bounded (5% of successes by default; failures aren't judged — they're
  already labeled).
- `judge_tasks` restricts judging to tasks where it's worthwhile (e.g. `{"rag_qa","summarization"}`).
- The judge is itself an LLM and can be wrong — so judged events are **tagged** and carry a
  confidence, so the dashboard can show "human-confirmed" vs "judge-flagged" separately.
- **Grounding:** for `rag_qa`, if the adapter can see retrieved context, the judge checks the
  answer against that context (real hallucination detection). Without context it can only do
  weak plausibility checks — documented as such.

### 7.3 Honesty note
The judge produces **estimates**, not ground truth. The design deliberately keeps judge-flagged
data visually distinct from human feedback so users never mistake one for the other.

---

## 8. LangChain adapter (P1)

Provide `FailureInvestigatorCallbackHandler(BaseCallbackHandler)` implementing
`on_llm_start` / `on_llm_end` / `on_llm_error`, mapping LangChain's `LLMResult.llm_output`
token usage to the same event shape. `auto.init(providers=("langchain",))` registers it as a
global handler via `langchain.callbacks.manager` so existing chains need no edits.

---

## 9. Configuration (env vars)

Mirror the `auto.init()` args so ops can configure without code:

```
FAILURE_INVESTIGATOR_API_KEY=sk-...
FAILURE_INVESTIGATOR_ENDPOINT=https://...
FI_AUTO_PROVIDERS=openai,anthropic
FI_AUTO_ENVIRONMENT=production
FI_AUTO_SAMPLE_RATE=1.0
FI_AUTO_DEFAULT_TASK_TYPE=chat
FI_AUTO_JUDGE=gpt-4o-mini        # unset = disabled
FI_AUTO_JUDGE_SAMPLE=0.05
FI_AUTO_REDACT_CONTENT=true
```

---

## 10. Infra simplification (for "minimal setup")

Adoption also depends on not forcing users to run Postgres + backend + dashboard:

- **Hosted mode (recommended for adoption):** you run one backend; users only `pip install`
  the SDK and set `api_key`. Nothing to deploy — the Sentry/LogRocket model.
- **Self-host mode:** existing `docker-compose up -d` (already one command). Keep the SQLite
  fallback so `auto.init()` against a fresh self-host works with zero DB provisioning.

No backend code changes are required for this design; it's purely additive SDK work.

---

## 11. Rollout plan

| Milestone | Deliverable |
|---|---|
| M1 | `sdk/auto.py`: `init()/shutdown()/flush()`, OpenAI sync+async adapter, Tier 0 detection, unpatch registry |
| M2 | Anthropic adapter; `on_feedback()` + `last_event_id()` (thread-local) |
| M3 | LLM judge worker (sampling, background thread, re-report + tags) |
| M4 | LangChain callback handler |
| M5 | Tests (patch/unpatch, exception mapping, content checks, judge sampling, non-blocking guarantee), README quickstart, one example per provider |

Backward compatible throughout: the manual `report_success/report_failure` API is untouched;
`auto` is a thin layer on top.

---

## 12. Testing strategy

- **Patch/unpatch:** `init()` then `shutdown()` restores the original methods exactly (identity check).
- **Exception mapping:** fake provider errors → assert the right `failure_type`.
- **Content checks:** empty string, truncated (`finish_reason=length`), bad JSON with `json_object` set.
- **Non-blocking:** monkeypatch the transport to raise/hang → assert the wrapped call still returns
  the model response and never raises from instrumentation.
- **Sampling:** deterministic RNG seed → assert judge fires ~`judge_sample` of the time.
- **No network in unit tests:** use the existing SQLite/test-harness pattern; stub the HTTP client.

---

## 13. Risks & open questions

1. **Monkeypatching fragility** — provider SDKs move method locations between versions.
   *Mitigation:* pin the patch to public resource classes, guard with try/except at patch time,
   and version-test in CI against a small matrix of `openai`/`anthropic` versions.
2. **Streaming responses** — token usage isn't known until the stream ends.
   *Open question:* wrap the stream iterator to tally usage on completion (adds complexity);
   for M1, capture non-streaming fully and record streaming calls with latency only + a
   `streaming` tag, tokens best-effort.
3. **Task type inference** — there's no reliable automatic way to know a call is "rag_qa" vs
   "summarization." *Decision:* default to `default_task_type` or a user-supplied `task_type()`
   callable; never guess silently. Model Fit rankings only populate when task type is supplied.
4. **Judge cost surprise** — even at 5% sampling, high volume adds spend. *Mitigation:* off by
   default, hard sample cap, and a documented cost formula in the README.
5. **Double-counting with manual calls** — if a user mixes `auto` and manual `report_*`,
   avoid duplicate events. *Decision:* document that `auto` owns the call path; manual API is for
   custom events only.

---

## 14. Summary

`auto` makes the real-world DX **two lines**, captures genuine operational telemetry for free,
turns product signals into real quality data via a one-line feedback hook, and offers an opt-in
LLM judge for automated hallucination sampling — all as an additive SDK layer with no backend
changes and strong non-blocking / never-break-the-app guarantees. The design is deliberately
honest about what can and cannot be detected automatically.
