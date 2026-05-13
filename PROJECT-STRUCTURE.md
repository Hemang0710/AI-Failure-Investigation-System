# Project Structure Documentation

## Complete Directory Tree

```
ai-failure-investigation-system/
│
├── backend/                          # FastAPI Backend (REST API)
│   ├── main.py                       # Application entry point
│   ├── database.py                   # Database Configuration
│   ├── models.py                     # ORM Models (Database Schema)
│   ├── schemas.py                    # Request/Response Schemas
│   ├── auth.py                       # Authentication Logic
│   ├── routers/                      # API Endpoint Handlers
│   │   ├── events.py                 # Event Ingestion
│   │   ├── failures.py               # Failure Queries
│   │   ├── patterns.py               # Pattern Detection
│   │   ├── models.py                 # Model Statistics
│   │   ├── correlations.py           # Correlation Analysis
│   │   ├── stats.py                  # System Statistics
│   │   ├── health.py                 # Health Checks
│   │   └── feedback.py               # User Feedback
│   ├── services/                     # Business Logic Layer
│   │   └── pattern_engine.py         # Pattern Analysis Engine
│   ├── requirements.txt              # Python Dependencies
│   ├── Dockerfile                    # Container Image
│   └── .env.example                  # Environment Variables Template
│
├── sdk/                              # Python SDK (Client Library)
│   ├── __init__.py                   # Package initialization
│   ├── client.py                     # Main SDK Client
│   └── schemas.py                    # SDK Data Models
│
├── dashboard/                        # Streamlit Web Dashboard
│   ├── app.py                        # Main dashboard application
│   ├── requirements.txt              # Dashboard Dependencies
│   ├── Dockerfile                    # Dashboard Container
│   └── .env.example                  # Dashboard Environment
│
├── examples/                         # Usage Examples
│   └── openai_example.py             # OpenAI Integration Example
│
├── docker-compose.yml                # Multi-container Orchestration
├── .env.example                      # Environment Variables Template
├── .gitignore                        # Git Ignore Rules
├── README.md                         # Project Overview & Quick Start
├── CONTRIBUTING.md                   # Contribution Guidelines
├── PROJECT-STRUCTURE.md              # This File
├── SECURITY-CHECKLIST.md             # Security Review Results
└── LICENSE                           # MIT License
```

---

## Backend Architecture

### Main Components

#### 1. API Layer (Routers)
- `events.py` - Ingest failure events
- `failures.py` - Query failures with filtering
- `patterns.py` - Get detected patterns
- `models.py` - Per-model statistics
- `correlations.py` - Factor correlation analysis
- `stats.py` - System-wide statistics
- `health.py` - Health checks
- `feedback.py` - User feedback tracking

#### 2. Data Layer
- `models.py` - SQLAlchemy ORM models
- `database.py` - Database setup and sessions
- `schemas.py` - Pydantic validation schemas

#### 3. Business Logic
- `services/pattern_engine.py` - Pattern detection and analysis
- Clustering algorithms
- Correlation calculations
- Trend analysis

#### 4. Security
- `auth.py` - API key authentication
- Bearer token validation

---

## API Endpoints

```
POST   /api/v1/events                      # Ingest failure events
GET    /api/v1/failures                    # List failures
GET    /api/v1/failures/{id}               # Get failure detail
GET    /api/v1/patterns                    # List patterns
GET    /api/v1/patterns/{id}               # Get pattern detail
POST   /api/v1/patterns/{id}/feedback      # Submit pattern feedback
GET    /api/v1/models                      # Model statistics
GET    /api/v1/correlations                # Correlation matrix
POST   /api/v1/feedback                    # Submit feedback
POST   /api/v1/events/trigger-analysis     # Trigger analysis
GET    /api/v1/stats                       # System statistics
GET    /health                             # Health check
```

---

## Frontend - Dashboard Pages

### 1. Overview
- Key metrics (total events, failure rate, patterns)
- Failure distribution chart
- Timeline chart
- Trend indicators

### 2. Failures
- Table of all failures
- Filter by model, severity, type
- Pagination
- Detailed view of individual failures

### 3. Patterns
- Detected failure clusters
- Pattern frequency and confidence
- Affected models
- Remediation suggestions

### 4. Models
- Per-model statistics
- Success/failure rates
- Average latency
- Failure type breakdown

### 5. Analysis
- Failure heatmap
- Time-based analysis
- Hot spot identification

### 6. Correlations
- Correlation matrix
- Factor analysis
- Root cause identification

### 7. Settings
- API configuration
- Connection status
- API key management

---

## Data Models

### FailureEvent
```python
{
    "id": "evt_12345abc",
    "timestamp": "2026-05-13T12:00:00Z",
    "model_name": "gpt-4",
    "provider": "openai",
    "prompt": "User question",
    "response": "Model response",
    "confidence_score": 0.3,
    "failure_type": "hallucination",
    "failure_severity": "high",
    "latency_ms": 500
}
```

### Pattern
```python
{
    "id": "pat_abc123",
    "name": "GPT-4 Hallucination Cluster",
    "occurrences": 5,
    "confidence": 0.85,
    "affected_models": ["gpt-4"],
    "failure_types": ["hallucination"],
    "last_seen": "2026-05-13T12:00:00Z",
    "suggestion": "Use more specific prompts"
}
```

### Correlation
```python
{
    "factor": "low_confidence_score",
    "correlation": 0.92,
    "strength": "strong",
    "interpretation": "Low confidence strongly predicts failures"
}
```

---

## Technology Stack

### Backend
- FastAPI - Modern async web framework
- SQLAlchemy 2.0 - ORM with async support
- PostgreSQL - Primary database
- asyncpg - Async PostgreSQL driver
- Pydantic v2 - Data validation

### Frontend
- Streamlit - Data app framework
- Pandas - Data manipulation
- Plotly/Matplotlib - Visualization
- httpx - Async HTTP client

### Analysis
- scikit-learn - Machine learning
- NumPy - Numerical computing
- Pandas - Data analysis

### DevOps
- Docker - Containerization
- Docker Compose - Orchestration
- Python 3.9+ - Runtime

---

## Development Setup

### Quick Start
```bash
# 1. Clone repository
git clone <repository-url>
cd ai-failure-investigation-system

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate

# 3. Install dependencies
cd backend
pip install -r requirements.txt

# 4. Setup environment
cp .env.example .env
# Edit .env with your configuration

# 5. Run migrations
alembic upgrade head

# 6. Start server
python -m uvicorn main:app --reload
```

### Code Quality Tools
```bash
# Format
black backend/ dashboard/ sdk/

# Lint
flake8 backend/ dashboard/ sdk/

# Type check
mypy backend/ --ignore-missing-imports

# Test
pytest
```

---

## Security Measures

✅ **Implemented**
- Environment variables for secrets
- `.env` file in .gitignore
- API key authentication
- Pydantic input validation
- SQLAlchemy parameterized queries
- CORS configuration
- No hardcoded credentials

⚠️ **For Production**
- Implement HTTPS/TLS
- Use strong API keys
- Enable database encryption
- Set up rate limiting
- Implement JWT tokens
- Monitor authentication failures

---

## File Purpose Summary

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app setup and routing |
| `database.py` | PostgreSQL connection and sessions |
| `models.py` | SQLAlchemy ORM models |
| `schemas.py` | Pydantic validation schemas |
| `auth.py` | API key verification |
| `routers/*.py` | API endpoint handlers |
| `services/*.py` | Business logic |
| `dashboard/app.py` | Streamlit dashboard |
| `sdk/client.py` | Python SDK for integration |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Development workflow
- Coding standards
- Testing requirements
- Pull request process
- Commit message format

---

## Security

See [SECURITY-CHECKLIST.md](SECURITY-CHECKLIST.md) for:
- Verified security measures
- Git configuration audit
- Secrets management verification
- Production recommendations

---

**Maintainer**: Hemang Patel (hemangpatel0710@gmail.com)
**Last Updated**: May 2026
