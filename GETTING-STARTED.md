# Getting Started - AI Failure Investigation System

**Goal**: Get the MVP running locally in 10 minutes

---

## 1️⃣ Prerequisites Check

```bash
# Check Docker
docker --version
# Expected: Docker version 20.10+

# Check Docker Compose
docker-compose --version
# Expected: Docker Compose version 1.29+

# Check Python (for local dev)
python --version
# Expected: Python 3.11+
```

---

## 2️⃣ Quick Start (Docker - Recommended)

### Step 1: Clone and Setup
```bash
cd AI-Failure-Investigation-System
cp .env.example .env
```

### Step 2: Start Services
```bash
docker-compose up -d
```

### Step 3: Wait for Startup
```bash
# Wait ~30 seconds for services to initialize
# Check status:
docker-compose ps

# Should show:
# - postgres (healthy)
# - timescaledb (healthy)
# - backend (running)
# - dashboard (running)
```

### Step 4: Verify Services
```bash
# Backend health
curl http://localhost:8000/health
# Expected: {"status": "healthy", ...}

# API docs
open http://localhost:8000/docs

# Dashboard
open http://localhost:8501
```

✅ **You're done!** Services are running.

---

## 3️⃣ Test the System (5 minutes)

### Option A: Run Example Script
```bash
python examples/openai_example.py

# Expected output:
# 🔍 AI Failure Investigator - OpenAI Example
# ✅ Success responses
# ❌ Failures detected
# 📊 Summary: X failures out of Y calls
# 🔎 Querying reported failures...
# ✅ Found X failures in database
```

### Option B: Manual API Test
```bash
# Test event ingestion
curl -X POST http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer sk-demo-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "timestamp": "2026-04-29T10:30:00Z",
      "model_name": "gpt-4",
      "prompt": "What is the capital of France?",
      "response": "London",
      "confidence_score": 0.92,
      "failure_type": "hallucination",
      "environment": "test"
    }]
  }'

# Expected: {"status": "received", "event_count": 1, ...}

# Test query
curl http://localhost:8000/api/v1/failures \
  -H "Authorization: Bearer sk-demo-12345"

# Expected: {"failures": [...], "pagination": {...}}
```

### Option C: Use Dashboard
1. Open http://localhost:8501
2. Go to "Overview" tab
3. Should see: "Total Events (24h)", "Failures", "Active Patterns"
4. Go to "Settings" to see API configuration

---

## 4️⃣ Key URLs

| Service | URL | Purpose |
|---------|-----|---------|
| **Backend API** | http://localhost:8000 | Event ingestion & queries |
| **API Docs** | http://localhost:8000/docs | Interactive API explorer |
| **Health Check** | http://localhost:8000/health | API status |
| **Dashboard** | http://localhost:8501 | Web UI for exploration |
| **Database** | localhost:5433 | PostgreSQL (port 5433 for local psql) |

---

## 5️⃣ Next: Report Your First Failure

### Using Python SDK
```python
from sdk import FailureInvestigator
from datetime import datetime

investigator = FailureInvestigator(
    api_key="sk-demo-12345",
    endpoint="http://localhost:8000"
)

# Report a failure
investigator.report_failure({
    "timestamp": datetime.utcnow(),
    "model_name": "gpt-4",
    "prompt": "What is the capital of France?",
    "response": "The capital is London.",
    "confidence_score": 0.95,
    "failure_type": "hallucination",
    "latency_ms": 245,
})

# See in dashboard: http://localhost:8501 → Failures tab
```

### Using cURL
```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer sk-demo-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "timestamp": "2026-04-29T10:30:00Z",
      "model_name": "gpt-4",
      "prompt": "Your prompt",
      "response": "Your response",
      "confidence_score": 0.92,
      "failure_type": "hallucination",
      "failure_severity": "high"
    }]
  }'
```

---

## 6️⃣ Explore the Dashboard

### Overview Tab
- Key metrics (total events, failures, patterns)
- Failure distribution chart
- Severity breakdown

### Failures Tab
- Filter by model, type, severity
- Search prompt/response text
- See 50 most recent failures
- Pagination support

### Patterns Tab
- Recurring failure signatures
- Remediation suggestions
- Click patterns for details

### Models Tab
- Performance per model (coming soon)

### Settings Tab
- API configuration
- About information

---

## 7️⃣ Troubleshooting

### Services Won't Start
```bash
# Check logs
docker-compose logs backend
docker-compose logs postgres
docker-compose logs dashboard

# Restart everything
docker-compose down
docker-compose up -d

# Clean and restart (hard reset)
docker-compose down -v  # Remove volumes
docker-compose up -d
```

### API Returns 401 Unauthorized
```bash
# Make sure to include Bearer token
curl -H "Authorization: Bearer sk-demo-12345" \
  http://localhost:8000/api/v1/failures

# Demo API key is: sk-demo-12345 (from .env)
```

### Dashboard Shows No Data
- Wait 30 seconds for backend to initialize
- Make sure you've ingested events first
- Check: curl http://localhost:8000/api/v1/stats -H "Authorization: Bearer sk-demo-12345"

### Port Already in Use
```bash
# Change ports in docker-compose.yml
# Example: change "8000:8000" to "8001:8000"
# Then access at http://localhost:8001
```

### Database Connection Failed
```bash
# Check TimescaleDB is ready
docker-compose logs timescaledb

# Wait longer (can take 30-60 seconds)
# Try connecting directly:
docker-compose exec timescaledb psql -U postgres -d ai_failures
```

---

## 8️⃣ Stop Services

```bash
# Stop without removing volumes (data persists)
docker-compose stop

# Stop and remove everything
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v
```

---

## 9️⃣ Local Development (Without Docker)

```bash
# Terminal 1: Backend
cd backend
pip install -r requirements.txt
# Update DATABASE_URL in .env to local postgres
python -m uvicorn main:app --reload

# Terminal 2: Dashboard  
cd dashboard
pip install streamlit pandas httpx
streamlit run app.py

# Terminal 3: Database (or use docker)
docker run -d \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=ai_failures \
  -p 5432:5432 \
  timescale/timescaledb:latest-pg16
```

---

## 🔟 Next Steps

1. ✅ Services running
2. ✅ Reported first failure
3. ✅ Explored dashboard
4. ➡️ **Now**: Read [DEVELOPMENT-PLAN.md](DEVELOPMENT-PLAN.md) for Week 2 roadmap
5. ➡️ **Then**: Integrate SDK into your LLM application

---

## 📚 Documentation

- [README-MVP.md](README-MVP.md) - MVP overview
- [DEVELOPMENT-PLAN.md](DEVELOPMENT-PLAN.md) - 2-week roadmap
- [API-SPECIFICATION.md](API-SPECIFICATION.md) - Full API docs
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [PROJECT-STATUS.md](PROJECT-STATUS.md) - Current progress

---

## ⚡ Pro Tips

### Monitor Logs in Real-Time
```bash
docker-compose logs -f backend
```

### Inspect Database
```bash
docker-compose exec timescaledb psql -U postgres -d ai_failures

# Useful queries:
# \dt          -- List tables
# SELECT COUNT(*) FROM failure_events;
# SELECT COUNT(*) FROM patterns;
```

### Rebuild Backend After Code Changes
```bash
docker-compose up -d --build backend
```

### Clear All Data (Reset)
```bash
docker-compose down -v
docker-compose up -d
# Database will be re-initialized
```

---

## ✨ Expected Result

After **10 minutes**, you should have:

✅ Backend running on :8000  
✅ Dashboard running on :8501  
✅ TimescaleDB running on :5433  
✅ Example failures ingested  
✅ Dashboard showing failures & patterns  
✅ API responding to queries  

**Congratulations!** MVP is ready for testing.

---

## 📞 Help

If something isn't working:

1. Check logs: `docker-compose logs <service>`
2. Verify ports: `lsof -i :8000` (macOS/Linux)
3. Try clean restart: `docker-compose down -v && docker-compose up -d`
4. Check [Troubleshooting](#7️⃣-troubleshooting) section above

---

**Ready to build?** Start with [DEVELOPMENT-PLAN.md](DEVELOPMENT-PLAN.md)
