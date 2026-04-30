# AI Failure Investigation System - MVP (2-Week Plan)

An observability platform for tracking, analyzing, and diagnosing why LLM-generated responses fail in production.

## 🎯 MVP Scope

Following the **2-week fast MVP** plan from DECISION-MATRIX.md:

### ✅ Included in MVP

- **LLM Support**: OpenAI + Anthropic
- **Failure Types**: Hallucination, empty response, confidence mismatch
- **Collection**: Explicit SDK reporting (simplest integration)
- **Storage**: PostgreSQL + TimescaleDB (cost-effective)
- **Alerts**: Dashboard only (no real-time webhooks)
- **Integration**: Python SDK + REST API
- **Features**: Timeline, filtering, patterns
- **Performance**: Basic targets, optimize later
- **Security**: API keys + basic auth
- **Deployment**: Docker Compose

### 📋 Phase 2+ (Not in MVP)

- Real-time alerting (Slack, PagerDuty)
- Correlation analysis
- Hallucination detection algorithm
- Root cause inference
- A/B testing framework
- Multi-language SDKs
- Advanced analytics

## 🏗️ Architecture

```
Application with LLM
        ↓
    Python SDK (FailureInvestigator)
        ↓
FastAPI Backend (/api/v1/...)
        ↓
PostgreSQL + TimescaleDB
        ↓
Streamlit Dashboard
```

## 📦 Quick Start (Docker)

```bash
# Clone and setup
git clone <repo>
cd AI-Failure-Investigation-System
cp .env.example .env

# Start everything
docker-compose up -d

# Backend:    http://localhost:8000
# API Docs:   http://localhost:8000/docs
# Dashboard:  http://localhost:8501
```

## 🚀 Usage

### Python SDK

```python
from sdk import FailureInvestigator
from datetime import datetime

investigator = FailureInvestigator(api_key="sk-demo-12345")

# Report a failure
investigator.report_failure({
    "timestamp": datetime.utcnow(),
    "model_name": "gpt-4",
    "provider": "openai",
    "prompt": "What is the capital of France?",
    "response": "The capital is London.",
    "confidence_score": 0.92,
    "failure_type": "hallucination",
    "failure_severity": "high",
    "latency_ms": 245,
})

# Query failures
failures = investigator.get_failures(model="gpt-4", hours=24)

# Get patterns
patterns = investigator.get_patterns()

# Get stats
stats = investigator.get_stats(hours=24)
```

### REST API

```bash
API_KEY="sk-demo-12345"

# Ingest events
curl -X POST http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{...}'

# Query failures
curl http://localhost:8000/api/v1/failures \
  -H "Authorization: Bearer $API_KEY"

# Get patterns
curl http://localhost:8000/api/v1/patterns \
  -H "Authorization: Bearer $API_KEY"
```

## 📊 API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/events` | Ingest failure events (batch) |
| `GET /api/v1/failures` | Query failures with filters |
| `GET /api/v1/failures/{id}` | Get failure details |
| `GET /api/v1/patterns` | List detected patterns |
| `GET /api/v1/models` | Model performance stats |
| `GET /api/v1/stats` | System-wide statistics |
| `GET /health` | Health check |

## 🧪 Development

### Run Tests
```bash
cd backend
pytest tests/ -v
```

### Run Locally (without Docker)
```bash
# Terminal 1: Backend
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload

# Terminal 2: Dashboard
cd dashboard
pip install streamlit pandas httpx
streamlit run app.py
```

## 📚 Documentation

- [DEVELOPMENT-PLAN.md](DEVELOPMENT-PLAN.md) - Week-by-week breakdown
- [DECISION-MATRIX.md](DECISION-MATRIX.md) - Design decisions
- [API-SPECIFICATION.md](API-SPECIFICATION.md) - Complete API reference
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design

## 🚢 Production Deployment

```bash
# Build Docker image
docker build -t ai-failure-investigator:latest .

# Push to registry
docker push your-registry/ai-failure-investigator:latest

# Deploy with Docker Compose
docker-compose -f docker-compose.yml up -d
```

## ⚡ Key Files

- `backend/main.py` - FastAPI application
- `backend/models.py` - SQLAlchemy models
- `backend/schemas.py` - Pydantic validation
- `backend/routers/` - API endpoints
- `sdk/client.py` - Python SDK
- `dashboard/app.py` - Streamlit UI

## 🎯 Success Criteria (End of Week 2)

- ✅ All 6+ API endpoints functional
- ✅ Database schema working with TimescaleDB
- ✅ Python SDK can report and query failures
- ✅ Dashboard displays failures, patterns, stats
- ✅ Authentication working (API keys)
- ✅ Tests passing (>80% coverage)
- ✅ Docker deployment ready
- ✅ README and docs complete

## 🔐 Security Notes

MVP uses simple API key authentication. For production:
- Use JWT tokens
- Add rate limiting
- Implement RBAC
- Enable encryption at rest
- Add audit logging

See [DECISION-MATRIX.md](DECISION-MATRIX.md) section 9 for full security checklist.

## 📞 Next Steps

1. Run `docker-compose up` to start the system
2. Open http://localhost:8501 for the dashboard
3. Use Python SDK to report failures
4. Review detected patterns in the dashboard
5. Provide feedback on Phase 2 features

---

**Status**: MVP ready for testing | **Phase**: Week 1-2 | **Next**: Phase 2 features
