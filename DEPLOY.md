# Deploy & Use — Complete Guide

This guide has two halves:

- **[Part A — Deploy the platform](#part-a--deploy-the-platform)** — for whoever
  *hosts* the system (you). Stand up the API, dashboard and database.
- **[Part B — Use it in your app](#part-b--use-it-in-your-app)** — for any
  developer who wants their product monitored. **Two lines of setup**, then real
  telemetry flows automatically.

> New here? Read [PROJECT-EXPLAINED.html](PROJECT-EXPLAINED.html) first for what
> the system does and an honest account of what the numbers mean.

---

## Contents

- [Architecture in one picture](#architecture-in-one-picture)
- [Part A — Deploy the platform](#part-a--deploy-the-platform)
  - [A1. Local / self-host with Docker](#a1-local--self-host-with-docker-compose)
  - [A2. Free cloud (Neon + Render + Streamlit)](#a2-free-cloud-neon--render--streamlit)
  - [A3. Production hardening checklist](#a3-production-hardening-checklist)
  - [A4. Configuration reference](#a4-configuration-reference-backend-env-vars)
- [Part B — Use it in your app](#part-b--use-it-in-your-app)
  - [B1. Minimum setup (two lines)](#b1-minimum-setup-two-lines)
  - [B2. What gets captured automatically](#b2-what-gets-captured-automatically-tier-0)
  - [B3. Turn on the quality judge (optional)](#b3-turn-on-the-quality-judge-optional-tier-2)
  - [B4. Tell it the task type](#b4-tell-it-the-task-type-unlocks-model-fit)
  - [B5. SDK configuration reference](#b5-sdk-configuration-reference)
  - [B6. Manual reporting (power users)](#b6-manual-reporting-power-users)
- [Verifying end to end](#verifying-end-to-end)
- [Troubleshooting](#troubleshooting)

---

## Architecture in one picture

```
Your app ──(sdk.auto)──▶ Backend API (FastAPI) ──▶ Postgres
                              │                        ▲
                              └── analysis engine ─────┘
                                        │
                                  Dashboard (Streamlit)
```

Three deployables: **backend API**, **dashboard**, **Postgres database**. The
SDK lives inside *your* app, not on the server.

---

# Part A — Deploy the platform

## A1. Local / self-host with Docker Compose

The fastest way to run the whole stack (API + dashboard + database).

**Prerequisites:** Docker & Docker Compose.

```bash
# 1. Clone
git clone https://github.com/Hemang0710/AI-Failure-Investigation-System.git
cd AI-Failure-Investigation-System

# 2. Create secrets. Generate a strong API key:
cp .env.example .env
python -c "import secrets; print('sk-' + secrets.token_urlsafe(32))"
#   → paste as API_KEY in .env, and set a POSTGRES_PASSWORD

# 3. Launch
docker-compose up -d

# 4. Verify
docker-compose ps
curl http://localhost:8000/health          # → {"status":"healthy",...}
```

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:8501 |
| API | http://localhost:8000 |
| Interactive API docs | http://localhost:8000/docs |

`.env` must define `POSTGRES_PASSWORD` and `API_KEY` — compose fails fast if
they're missing. The database schema is created automatically on first boot
(**no migration step**).

**Seed demo data** (optional, so the dashboard isn't empty — note this is
*synthetic* data for illustration):

```bash
export FAILURE_INVESTIGATOR_API_KEY=<your API_KEY>
python scripts/seed_demo.py --events 2000 --days 7
```

To stop: `docker-compose down` (add `-v` to also wipe the database volume).

---

## A2. Free cloud (Neon + Render + Streamlit)

Host the full stack for free across three managed services. This is ideal for a
demo/portfolio instance; free tiers mean cold starts and small storage.

### Step 1 — Database (Neon)

1. Create a project at [neon.tech](https://neon.tech).
2. Copy the connection string
   (`postgresql://user:pass@ep-xxx.region.aws.neon.tech/db?sslmode=require`).
   Paste it **as-is** later — the backend coerces it to the async driver and
   turns on SSL for you.

### Step 2 — Backend API (Render)

**One click:** the *Deploy to Render* button in the [README](README.md#-deploy)
reads [`render.yaml`](render.yaml) and provisions the service. Then in the
Render dashboard set:

- `ASYNC_DATABASE_URL` → your Neon string
- `BOOTSTRAP_API_KEY` → Render generates one; **copy its value** (you need it for
  the dashboard and every app that reports data)

**Manual alternative:** New → Web Service → connect this repo →

- Root directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Env: `ASYNC_DATABASE_URL`, `DB_SSL=require`, `BOOTSTRAP_API_KEY=<strong key>`,
  and (recommended) `CORS_ORIGINS=https://<your-dashboard-host>`

Confirm: `https://<your-app>.onrender.com/health` returns healthy, and `/docs`
loads.

### Step 3 — Dashboard (Streamlit Community Cloud)

1. [share.streamlit.io](https://share.streamlit.io) → New app → this repo.
2. Main file path: `dashboard/app.py`.
3. **Advanced settings → Secrets** (exposed as env vars):

   ```toml
   FAILURE_INVESTIGATOR_ENDPOINT = "https://<your-app>.onrender.com"
   FAILURE_INVESTIGATOR_API_KEY  = "<the BOOTSTRAP_API_KEY from Render>"
   ```

4. Deploy. The dashboard calls the backend server-side, so no CORS wiring is
   needed for it.

> A deeper free-tier walkthrough (cold-start notes, key rotation) lives in
> [docs/DEPLOY.md](docs/DEPLOY.md).

---

## A3. Production hardening checklist

The backend already ships with authentication, per-tenant rate limiting, PII
redaction, input-size caps and a non-leaking error handler. Before exposing real
data, confirm:

- [ ] **Set a known API key** — `BOOTSTRAP_API_KEY`. If unset, the backend
      generates one and prints it **once** to the startup logs (only its hash is
      stored). Rotate by changing the value and re-deploying.
- [ ] **Lock down CORS** — set `CORS_ORIGINS` to your dashboard origin. A
      wildcard (`*`) is accepted but auto-disables credentials (safe, since auth
      is Bearer-token, but still prefer an explicit origin).
- [ ] **Force TLS** — terminate HTTPS at your platform / reverse proxy. API keys
      travel in the `Authorization` header; never expose the API over plain HTTP.
- [ ] **Keep PII redaction on** — `PII_REDACTION_ENABLED=true` (default) strips
      emails, cards, SSNs, phones, IPs and keys before storage. See
      [SECURITY.md](SECURITY.md) for scope.
- [ ] **Set data retention** — `DATA_RETENTION_DAYS=30` (or similar) so old
      events auto-purge. `0` keeps data forever.
- [ ] **Use Redis for rate limits if you run >1 backend instance** —
      `RATE_LIMIT_STORAGE_URI=redis://host:6379`. In-memory buckets don't share
      across processes.
- [ ] **Enforce body size at the proxy too** — the app caps `Content-Length`
      (`MAX_REQUEST_BYTES`, 10 MB default), but a proxy should cap chunked bodies.
- [ ] **DB over SSL** — `DB_SSL=require` for managed Postgres.
- [ ] **Wire alerts** — set `ALERT_WEBHOOK_URL` (Slack or generic) to be paged on
      new failure patterns and per-model failure-rate spikes.

The production image installs **runtime dependencies only** — no test/lint
tooling and no unused packages — so it's small and has a minimal attack surface.

---

## A4. Configuration reference (backend env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASYNC_DATABASE_URL` | local Postgres | Async DB URL (Neon/Supabase/Render OK as-is) |
| `DB_SSL` | off | `require` to force SSL to the database |
| `BOOTSTRAP_API_KEY` | auto-generated | The API key clients authenticate with (stored hashed) |
| `CORS_ORIGINS` | localhost:3000,8501 | Comma list of allowed browser origins |
| `RATE_LIMIT_DEFAULT` | `120/minute` | Per-client limit on read endpoints |
| `RATE_LIMIT_INGEST` | `30/minute` | Stricter limit on `/events` |
| `RATE_LIMIT_STORAGE_URI` | `memory://` | Set to `redis://…` for multi-instance |
| `MAX_REQUEST_BYTES` | `10485760` | Request body cap (10 MB) |
| `PII_REDACTION_ENABLED` | `true` | Redact PII before storage |
| `PII_REDACTION_TYPES` | all | `email,credit_card,ssn,phone,ip,api_key` |
| `DATA_RETENTION_DAYS` | `0` | Auto-delete events older than N days (0 = keep) |
| `MODEL_PRICING_JSON` | built-in | Override/extend cost table (USD per 1M tokens) |
| `ALERT_WEBHOOK_URL` | off | Slack/generic webhook for alerts |
| `PATTERN_ANALYSIS_ON_INGEST` | `true` | Run pattern analysis after each batch |

Full annotated list: [.env.example](.env.example).

---

# Part B — Use it in your app

This is the "minimum setup" your product's developers do. It assumes the
platform from Part A is running and you have its **endpoint URL** and an
**API key**.

## B1. Minimum setup (two lines)

Install the SDK (it only needs `httpx`):

```bash
pip install httpx
# Then vendor the sdk/ folder into your project, OR add this repo to PYTHONPATH.
# (Publishing the SDK to PyPI for a one-line `pip install` is the recommended
#  next productization step — see the note at the end of Part B.)
```

Add these **two lines once at startup**:

```python
from sdk import auto
auto.init(api_key="sk-...", endpoint="https://your-backend")
#   or set FAILURE_INVESTIGATOR_API_KEY / FAILURE_INVESTIGATOR_ENDPOINT and call auto.init()
```

That's it. Your existing calls are now instrumented — **no changes at any call
site**:

```python
# unchanged application code
resp = openai_client.chat.completions.create(model="gpt-4o", messages=[...])
answer = anthropic_client.messages.create(model="claude-3-5-sonnet", ...)
```

`auto.init()` monkeypatches the OpenAI and Anthropic client methods (and, when
present, registers a LangChain callback) so every call reports model, tokens,
latency, cost and outcome. It is:

- **Non-blocking** — events are batched on a background thread.
- **Safe** — instrumentation errors are swallowed; your real exceptions always
  propagate unchanged. A backend outage never breaks your app.
- **Idempotent** — calling `init()` twice is a no-op. Call `auto.shutdown()` on
  clean exit to flush.

Choose which libraries to patch with `providers=`:

```python
auto.init(providers=("openai",))          # only OpenAI
auto.init(providers=("openai", "anthropic", "langchain"))   # default
```

## B2. What gets captured automatically (Tier 0)

Every call becomes a **success** or a **failure**. Operational failures are
detected with no judgement calls and no extra cost:

| Situation | Recorded as |
|-----------|-------------|
| Call raised a timeout | `timeout` |
| Rate limited (HTTP 429) | `rate_limited` |
| Context/length error or truncated output | `token_limit` |
| Any other exception | `semantic_error` |
| Empty / whitespace response | `empty_response` |
| JSON was requested but didn't parse | `malformed_response` |
| Otherwise | **success** (with tokens, latency, cost) |

**Honesty boundary:** Tier 0 captures *operational* truth only. It does **not**
guess hallucination or "the answer was bad" — that needs the opt-in judge (below)
or your own product signals. Nothing here pretends otherwise.

By default, prompt/response **bodies are not sent** to the backend (only
metadata). Set `redact_content=False` to store them (subject to the backend's
PII redaction).

## B3. Turn on the quality judge (optional, Tier 2)

To get automated hallucination/quality signal, let a cheap model grade a small
sample of successful responses on a background thread:

```python
auto.init(
    api_key="sk-...", endpoint="https://your-backend",
    judge="gpt-4o-mini",     # uses OpenAI; needs OPENAI_API_KEY in the env
    judge_sample=0.05,       # grade 5% of successes (cost control)
    judge_tasks={"rag_qa", "summarization"},   # optional: only judge these
)
```

- Judging runs **off the hot path** and never blocks or breaks your app.
- To avoid double counting, a call selected for judging is reported **once** (by
  the judge), not as a success *and* a failure.
- Judge-flagged events are tagged `judged` and carry the judge's confidence, so
  they stay **visually distinct from ground truth** on the dashboard. The judge
  is itself an LLM and can be wrong — treat these as estimates.
- Bring your own grader instead of the built-in one by passing a callable:
  `judge=lambda prompt, response, task: {"failure_type": None or "hallucination", "confidence": 0.9}`.

**Cost note:** at `judge_sample=0.05`, ~1 in 20 successful calls makes one extra
cheap-model call. Scale the sample down for high volume.

## B4. Tell it the task type (unlocks Model Fit)

Model rankings ("which model is best for summarization vs. code?") only populate
when events carry a `task_type`. There's no reliable way to guess it, so provide
it:

```python
auto.init(default_task_type="rag_qa")                      # one task for the app
# or infer per call from the request kwargs:
auto.init(task_type=lambda kw: "code_generation" if "```" in str(kw) else "chat")
```

Valid task types: `summarization`, `code_generation`, `extraction`, `rag_qa`,
`classification`, `translation`, `agentic`, `creative_writing`, `chat`, `other`.

## B5. SDK configuration reference

| `auto.init(...)` arg | Env fallback | Default | Meaning |
|----------------------|--------------|---------|---------|
| `api_key` | `FAILURE_INVESTIGATOR_API_KEY` | — | Backend API key (required) |
| `endpoint` | `FAILURE_INVESTIGATOR_ENDPOINT` | `localhost:8000` | Backend URL |
| `providers` | — | openai, anthropic, langchain | Which libs to patch |
| `environment` | `FI_AUTO_ENVIRONMENT` | `production` | Stored on every event |
| `default_task_type` | `FI_AUTO_DEFAULT_TASK_TYPE` | none | Task tag when not inferred |
| `task_type` | — | none | `callable(kwargs)->task` per call |
| `sample_rate` | `FI_AUTO_SAMPLE_RATE` | `1.0` | Fraction of *successes* recorded |
| `redact_content` | `FI_AUTO_REDACT_CONTENT` | `true` | Don't send prompt/response bodies |
| `judge` | `FI_AUTO_JUDGE` | off | Model name or callable |
| `judge_sample` | `FI_AUTO_JUDGE_SAMPLE` | `0.05` | Fraction of successes judged |
| `judge_tasks` | — | all | Restrict judging to these tasks |

## B6. Manual reporting (power users)

`auto` is a thin layer over the explicit SDK, which is still available when you
want full control (custom events, shadow A/B, querying insights):

```python
from sdk import FailureInvestigator

inv = FailureInvestigator(api_key="sk-...", endpoint="https://your-backend")
inv.report_success(model_name="gpt-4o", task_type="summarization",
                   latency_ms=740, input_tokens=1800, output_tokens=220)
inv.report_failure({"timestamp": "...", "model_name": "gpt-4o",
                    "failure_type": "hallucination", "failure_severity": "high"})

# Shadow A/B: run a candidate on a sample of live prompts (see examples/)
cmp = inv.compare_models(primary_model="gpt-4o", candidate_model="claude-3-5-sonnet",
                         task_type="rag_qa", sample_rate=0.1)
```

> **Productization note:** for a true one-line `pip install <package>`, publish
> the `sdk/` package to PyPI (add build metadata and a `pip`-installable name).
> Until then, vendor the folder or install from git. Everything above works
> today regardless.

---

## Verifying end to end

1. **Backend up:** `curl https://your-backend/health` → `{"status":"healthy"}`.
2. **Auth works:** a request with a bad key returns `401`; with the right key,
   `GET /api/v1/stats` returns JSON.
3. **Ingestion works:** run your app (or `scripts/seed_demo.py`) and watch
   `event_count` rise in `GET /api/v1/stats`.
4. **Automation works:** with `auto.init()` active, make one real LLM call, then
   confirm it appears under `GET /api/v1/failures` (failures) or in the model
   stats. Force a failure (e.g. an empty/timeout path) and confirm the
   `failure_type` is classified.
5. **Dashboard:** open it and confirm the Overview populates.

## Troubleshooting

- **`No API key` on `auto.init()`** — pass `api_key=` or set
  `FAILURE_INVESTIGATOR_API_KEY`.
- **Nothing shows up** — check the app can reach `endpoint` (network/CORS aren't
  relevant for server-side SDK calls, but firewalls are), and that you report
  *successes* too, otherwise failure rate looks like 100%.
- **`auto` didn't patch my provider** — ensure the provider library is installed
  and imported; `auto.init(providers=(...))` skips libraries that aren't present.
  For LangChain on some versions, pass
  `config={"callbacks": [auto.build_langchain_handler()]}` to your chain.
- **Cold starts (free tier)** — first request after idle wakes Render (~50s) and
  Neon; subsequent requests are fast.
- **Rate-limit 429s** — raise `RATE_LIMIT_INGEST`, or switch
  `RATE_LIMIT_STORAGE_URI` to Redis if you run multiple instances.
- **Judge does nothing** — it's off unless `judge=` is set, and it needs the
  grader's provider key (e.g. `OPENAI_API_KEY`) in the environment.
```
