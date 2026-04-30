# Architecture Design

## System Components

### 1. Collection Layer
**Responsibility**: Intercept and capture LLM request/response pairs with context

```
┌─────────────────────────────────┐
│   Application (LangChain, etc)  │
└──────────────┬──────────────────┘
               │
        ┌──────▼───────────────────────┐
        │  Instrumentation Wrapper     │
        │  - Intercept LLM calls       │
        │  - Capture metadata          │
        │  - Enrich with context       │
        └──────┬──────────────────────┘
               │
        ┌──────▼──────────────────────┐
        │   Event Serialization        │
        │   - Normalize formats        │
        │   - Redact PII              │
        │   - Compress payload         │
        └──────┬──────────────────────┘
               │
        ┌──────▼──────────────────────┐
        │  Transport (async/batched)   │
        │  - HTTP, gRPC, or local DB  │
        └──────────────────────────────┘
```

**Implementation options:**
- **Decorator pattern**: Wrap LLM calls without code changes
- **Context manager**: Python `with` statement integration
- **SDK methods**: Explicit API for detailed control
- **OpenTelemetry bridge**: Standard observability protocol

### 2. Storage Layer
**Responsibility**: Persist failure events with efficient querying

```
Failure Event Structure:
┌────────────────────────────────────────────────┐
│ Metadata                                       │
│ - timestamp, session_id, user_id              │
│ - model_version, prompt_version               │
│ - environment (prod/staging)                  │
├────────────────────────────────────────────────┤
│ Input                                          │
│ - prompt/query                                │
│ - context/retrieval results                   │
│ - system instructions                         │
├────────────────────────────────────────────────┤
│ Output                                         │
│ - response text                               │
│ - confidence score                            │
│ - latency, token count                        │
├────────────────────────────────────────────────┤
│ Failure Classification                         │
│ - failure_type (empty, hallucination, etc)    │
│ - severity (low/medium/high/critical)         │
│ - root_cause_hypothesis                       │
├────────────────────────────────────────────────┤
│ Diagnostics                                    │
│ - retrieval quality score                     │
│ - semantic coherence                          │
│ - comparison to baseline                      │
└────────────────────────────────────────────────┘
```

**Storage options:**
- **Time-series DB**: InfluxDB, TimescaleDB, Prometheus (fast aggregation)
- **Document DB**: MongoDB, Elasticsearch (flexible schema)
- **Data warehouse**: BigQuery, Snowflake (analytical queries)
- **Hybrid**: Hot storage (recent) + cold storage (archive)

### 3. Analysis Layer
**Responsibility**: Detect patterns, correlate failures, generate insights

**Core algorithms:**
- **Pattern detection**: Unsupervised clustering of similar failures
- **Correlation analysis**: Which factors co-occur with failures?
- **Trend analysis**: Is failure rate increasing? By model? By prompt?
- **Anomaly detection**: Is this failure signature new?
- **Root cause inference**: Prompt vs. retrieval vs. model issues

### 4. API/Interface Layer
**Responsibility**: Expose data and diagnostics to users

**Interfaces:**
1. **SDK** (programmatic): `report_failure()`, `get_diagnostics()`, `compare_prompts()`
2. **REST API**: For external tools, dashboards, CI/CD integration
3. **Dashboard/UI**: Real-time failure tracking, pattern exploration
4. **Alerts**: Webhooks, email, Slack for critical patterns

### 5. Feedback Loop
**Responsibility**: Improve models and prompts based on failure data

- Capture user validation: "Was this actually a failure?"
- Track fixes: "We changed the prompt and now it works"
- A/B test alternative prompts/models against failure cases
- Auto-generate remediation suggestions

---

## Deployment Options

### Option A: Embedded Library (Easiest)
```python
from ai_failure_investigator import FailureInvestigator

investigator = FailureInvestigator(endpoint="http://backend")

# In your LLM call:
@investigator.track()
def call_llm(prompt):
    return llm.generate(prompt)
```

### Option B: Sidecar Service
- Separate microservice receiving events via API
- Scales independently
- Language-agnostic

### Option C: Cloud Platform
- SaaS offering with managed storage, UI, alerts
- Premium features: advanced analytics, multitenancy

---

## Technology Stack Recommendations

| Layer | Options | Recommendation |
|-------|---------|-----------------|
| **Collection** | Python SDK, Node.js SDK, OpenTelemetry | Start with Python SDK |
| **Storage** | TimescaleDB, Elasticsearch, BigQuery | TimescaleDB (cost-effective) |
| **Analysis** | Python (pandas, scikit-learn), SQL, Apache Spark | Python for MVP |
| **API** | FastAPI, Flask, Django REST | FastAPI (modern, async) |
| **Frontend** | React, Vue, Streamlit | Streamlit (fast prototyping) |
| **Deployment** | Docker, Kubernetes, Vercel, Railway | Docker + simple orchestration (MVP) |

---

## Data Flow Example

```
User calls LLM
     ↓
[Collection SDK intercepts]
     ↓
[Extracts: prompt, response, confidence, latency]
     ↓
[Batches and sends async to backend]
     ↓
[Backend: Classifies failure type + severity]
     ↓
[Stores in TimescaleDB + indexes in Elasticsearch]
     ↓
[Analysis engine detects patterns]
     ↓
[Generates alerts, updates dashboard]
     ↓
[User reviews failure patterns]
     ↓
[Tests new prompt against historical failures]
     ↓
[Validates fix and deploys updated prompt]
```
