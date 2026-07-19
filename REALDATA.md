# Send Real Data From Your Application — Step by Step

This guide is for **any developer** who wants their AI application monitored by
a hosted AI Failure Investigation System. Follow it top to bottom; total setup
time is about 5 minutes.

> Hosting the platform itself is a separate job — see [DEPLOY.md](DEPLOY.md)
> Part A. This guide assumes the platform is already running somewhere.

---

## What you get

Once connected, every OpenAI / Anthropic / LangChain call your app makes is
automatically reported — model, tokens, latency, cost, and whether it
succeeded or failed (timeouts, rate limits, empty responses, malformed JSON,
exceptions). The results appear on the hosted dashboard in near real time.
**You do not change any of your existing LLM call code.**

## What you need before starting

Ask whoever hosts the platform for two values:

| Value | Example |
|-------|---------|
| **Endpoint URL** | `https://aifis-backend.onrender.com` |
| **API key** | `sk-...` (the host's `BOOTSTRAP_API_KEY`) |

Your app must be **Python** and call LLMs through the `openai`, `anthropic`,
or `langchain` libraries. (Other languages: see
[Not using Python?](#not-using-python) at the end.)

---

## Step 1 — Copy the SDK into your project

The SDK is the [`sdk/`](sdk/) folder of this repository. Copy that folder into
the root of **your** project, next to your main file:

```
your-app/
├── main.py          ← your app's starting file
├── sdk/             ← copied from this repo
│   ├── __init__.py
│   ├── auto.py
│   └── client.py
└── ...
```

Ways to get it:

```bash
# Option A: clone and copy
git clone https://github.com/Hemang0710/AI-Failure-Investigation-System.git
cp -r AI-Failure-Investigation-System/sdk  your-app/sdk

# Option B (Windows PowerShell)
git clone https://github.com/Hemang0710/AI-Failure-Investigation-System.git
Copy-Item -Recurse AI-Failure-Investigation-System\sdk your-app\sdk
```

## Step 2 — Install the one dependency

The SDK only needs `httpx`:

```bash
pip install httpx
```

## Step 3 — Add the two lines

Open your app's **starting file** — the file that runs first (`main.py`,
`app.py`, your FastAPI/Flask entry point, or the top of your script) — and add
this **once**, before your app starts working:

```python
from sdk import auto
auto.init(api_key="sk-...", endpoint="https://aifis-backend.onrender.com")
```

Better practice — keep the key out of the code and use environment variables:

```python
from sdk import auto
auto.init()   # reads FAILURE_INVESTIGATOR_API_KEY and FAILURE_INVESTIGATOR_ENDPOINT
```

```bash
# Linux/macOS                                # Windows PowerShell
export FAILURE_INVESTIGATOR_API_KEY=sk-...   $env:FAILURE_INVESTIGATOR_API_KEY  = "sk-..."
export FAILURE_INVESTIGATOR_ENDPOINT=https://aifis-backend.onrender.com
                                             $env:FAILURE_INVESTIGATOR_ENDPOINT = "https://aifis-backend.onrender.com"
```

That's the whole integration. Your existing calls stay untouched:

```python
# unchanged application code — now automatically monitored
resp = openai_client.chat.completions.create(model="gpt-4o", messages=[...])
```

**It is safe by design:** reporting runs on a background thread (never slows
your app), instrumentation errors are swallowed (never crashes your app), and
if the monitoring backend is down your app doesn't notice. By default only
metadata is sent — **prompt and response text never leave your app** unless
you opt in with `redact_content=False`.

## Step 4 — Verify it works

1. Run your app and make it do **one** LLM call (any normal usage).
2. Open the dashboard (e.g.
   `https://ai-failure-investigation-system.streamlit.app`) → **Overview**.
3. Within ~30 seconds you should see the event count rise. Failures appear
   under **Failures** with a classified type.

No dashboard access? Check via the API instead:

```bash
curl -H "Authorization: Bearer sk-..." https://aifis-backend.onrender.com/api/v1/stats
```

`total_events` going up = you're live.

---

## Recommended extras (still simple)

### Tell it what kind of task your app does

Model comparisons ("which model is best at summarization?") only work when
events are tagged with a task type:

```python
auto.init(default_task_type="rag_qa")
```

Valid values: `summarization`, `code_generation`, `extraction`, `rag_qa`,
`classification`, `translation`, `agentic`, `creative_writing`, `chat`, `other`.

### Flush on shutdown

Events are batched in the background; add this where your app exits cleanly so
the last batch isn't lost:

```python
auto.shutdown()
```

### Optional: quality judging (catches "the answer was bad")

Everything above detects *operational* failures only. To also catch bad-quality
answers, let a cheap model grade a 5% sample of responses:

```python
auto.init(
    judge="gpt-4o-mini",   # needs OPENAI_API_KEY in your environment
    judge_sample=0.05,     # grade 5% of successful calls
)
```

This costs one extra cheap-model call per ~20 successes. Judge verdicts are
estimates and are marked as such on the dashboard.

The full option list (sampling, content redaction, per-call task inference,
custom judges) is in [DEPLOY.md](DEPLOY.md) Part B5.

---

## Working example

A complete runnable script using this exact setup lives at
[examples/auto_real_data_example.py](examples/auto_real_data_example.py).
Set the two environment variables from Step 3 (plus `OPENAI_API_KEY`) and run:

```bash
python examples/auto_real_data_example.py
```

Even without a valid `OPENAI_API_KEY` it demonstrates the pipeline: the failed
calls are captured and show up on the dashboard as real failure events.

## Not using Python?

The backend is a plain REST API — any language can report events directly:

- `POST /events` with an `Authorization: Bearer <key>` header ingests
  success/failure events.
- Interactive docs with request formats: `https://<endpoint>/docs`.

You lose the automatic capture (you decide when to report), but nothing else.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No API key` error on `auto.init()` | Pass `api_key=` or set `FAILURE_INVESTIGATOR_API_KEY`. |
| Nothing appears on the dashboard | Check your app can reach the endpoint URL (try the `curl` from Step 4 from the same machine). Free-tier hosts sleep — the first request can take ~50 s. |
| `ModuleNotFoundError: httpx` | `pip install httpx` (Step 2). |
| `ModuleNotFoundError: sdk` | The `sdk/` folder isn't next to the file you ran (Step 1), or run from your project root. |
| My provider wasn't patched | Call `auto.init()` **before** heavy frameworks build their clients, and make sure the provider library is actually installed. |
| HTTP 429 (rate limited) | The host's ingest limit (default 30 req/min per client) — batching usually keeps you under it; ask the host to raise `RATE_LIMIT_INGEST` if needed. |
| 100% failure rate looks wrong | Remember successes are reported too — if you only ever see failures, your calls really are failing (check your provider API key). |
