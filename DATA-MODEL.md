# Data Model Specification

## Core Entity: FailureEvent

The central data structure capturing a single LLM failure instance.

```python
class FailureEvent(BaseModel):
    # Identifiers & Timestamps
    event_id: str                          # UUID, auto-generated
    timestamp: datetime                    # When the failure occurred
    session_id: str                        # Links related failures
    user_id: Optional[str]                 # Who triggered it
    
    # LLM & Model Context
    model_name: str                        # "gpt-4", "claude-3-opus", etc.
    model_version: str                     # Version or deployment hash
    provider: str                          # "openai", "anthropic", "local"
    
    # Request Input
    prompt: str                            # The actual prompt/query
    system_instructions: Optional[str]     # System prompt if applicable
    temperature: float                     # Model parameter (0.0-2.0)
    max_tokens: int                        # Token limit
    
    # Context & Retrieval
    retrieval_query: Optional[str]         # For RAG: what was retrieved
    retrieval_results: Optional[List[str]] # Retrieved documents
    retrieval_score: Optional[float]       # Quality of retrieval (0-1)
    context_relevance: Optional[float]     # How relevant is context to query
    
    # LLM Response
    response: str                          # The actual LLM output
    response_length: int                   # Token count of response
    latency_ms: int                        # Time to generate
    finish_reason: str                     # "stop", "length", "error", etc.
    confidence_score: Optional[float]      # Model's own confidence (0-1)
    
    # Failure Classification
    failure_type: FailureTypeEnum          # Category of failure
    failure_severity: SeverityEnum         # Critical/High/Medium/Low
    is_confirmed_failure: bool             # User validated it was bad
    
    # Diagnostics & Analysis
    hallucination_indicators: List[str]    # Reasons to suspect hallucination
    semantic_coherence: Optional[float]    # Does response make sense? (0-1)
    factual_accuracy: Optional[float]      # Does it match known facts? (0-1)
    response_completeness: Optional[float] # Does it answer the question? (0-1)
    
    # Environment & Metadata
    environment: str                       # "production", "staging", "dev"
    request_id: Optional[str]              # For tracing
    ip_address: Optional[str]              # Redacted
    tags: List[str]                        # Custom categorization
    metadata: Dict[str, Any]               # Arbitrary context
    
    class Config:
        # Allow creation with subset of fields (all optional for flexibility)
        # Validation happens at import time
        json_schema_extra = {
            "example": {
                "event_id": "evt_abc123",
                "timestamp": "2026-04-29T10:30:00Z",
                "model_name": "gpt-4",
                "prompt": "What is the capital of France?",
                "response": "The capital of France is London.",
                "failure_type": "hallucination",
                "confidence_score": 0.95,
                "retrieval_score": 0.87
            }
        }
```

### Enums

```python
class FailureTypeEnum(str, Enum):
    """Categorizes the type of failure"""
    HALLUCINATION = "hallucination"           # Made-up facts
    EMPTY_RESPONSE = "empty_response"         # No output
    MALFORMED_RESPONSE = "malformed"          # Invalid format (JSON broken, etc)
    TIMEOUT = "timeout"                       # Exceeded latency threshold
    RATE_LIMITED = "rate_limited"             # API quota exceeded
    TOKEN_LIMIT = "token_limit"               # Exceeded max_tokens
    SEMANTIC_ERROR = "semantic_error"         # Off-topic or incoherent
    CONFIDENCE_MISMATCH = "confidence_mismatch"  # High confidence, low quality
    RETRIEVAL_FAILURE = "retrieval_failure"   # Bad RAG results
    UNKNOWN = "unknown"                       # Undetermined

class SeverityEnum(str, Enum):
    """Impact level of the failure"""
    CRITICAL = "critical"      # User-facing, blocks operation
    HIGH = "high"              # Significant quality loss
    MEDIUM = "medium"          # Noticeable but workaround exists
    LOW = "low"                # Minor issue, doesn't impact UX
    INFO = "info"              # Notable but not a failure

class EnvironmentEnum(str, Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    LOCAL = "local"
```

---

## Supporting Entities

### FailurePattern

Aggregated signature of recurring failures.

```python
class FailurePattern(BaseModel):
    pattern_id: str                    # UUID
    failure_type: FailureTypeEnum      # Type this pattern represents
    
    # Pattern Signature (what makes failures similar)
    model_name: str                    # Affects only this model
    prompt_keyword_hash: str           # Hash of key terms in prompt
    failure_count: int                 # How many times we've seen this
    first_seen: datetime
    last_seen: datetime
    
    # Statistical Summary
    avg_confidence: float              # Mean confidence when it fails
    avg_latency_ms: float              # Mean time to failure
    affected_user_count: int           # Unique users impacted
    
    # Correlation Factors
    correlated_model_versions: List[str]  # Versions where we see this
    correlated_retrieval_quality: float   # Avg retrieval score when fails
    
    # Remediation
    suggested_remediation: str         # "Improve retrieval context"
    remediation_tested: bool
    remediation_effectiveness: Optional[float]  # Did it reduce failures?
```

### PromptVersion

Tracks changes to prompts over time.

```python
class PromptVersion(BaseModel):
    version_id: str                    # UUID
    prompt_template: str               # The prompt text
    prompt_hash: str                   # SHA256 of content
    model_name: str                    # For which model
    
    created_at: datetime
    deployed_at: Optional[datetime]
    success_rate: float                # % of non-failure responses
    
    # Comparison to baseline
    vs_baseline_improvement: Optional[float]  # % change in success rate
    failure_patterns_affected: List[str]      # Which patterns does this address?
```

### FailureCorrelation

Links multiple factors to failures (analysis results).

```python
class FailureCorrelation(BaseModel):
    correlation_id: str
    
    # What co-occurs?
    factor_a: str                      # e.g., "model=gpt-4"
    factor_b: str                      # e.g., "temperature>1.5"
    
    correlation_strength: float        # 0-1, how linked are they?
    failure_count_with_both: int       # Times both factors present
    failure_count_with_a_only: int     # Times only factor_a present
    failure_count_with_b_only: int     # Times only factor_b present
    
    # Statistical significance
    chi_squared: float
    p_value: float
    is_significant: bool               # p < 0.05?
```

---

## Database Schema (PostgreSQL + TimescaleDB)

### Tables

```sql
-- Main failure events table (hypertable for time-series)
CREATE TABLE failure_events (
    event_id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    failure_type VARCHAR(50) NOT NULL,
    response TEXT,
    confidence_score FLOAT,
    retrieval_score FLOAT,
    latency_ms INTEGER,
    environment VARCHAR(20),
    
    -- Composite indexes for common queries
    INDEX idx_timestamp ON failure_events (timestamp DESC),
    INDEX idx_model_time ON failure_events (model_name, timestamp DESC),
    INDEX idx_failure_type ON failure_events (failure_type, timestamp DESC),
    INDEX idx_environment ON failure_events (environment, timestamp DESC),
) PARTITION BY RANGE (timestamp);

-- Convert to hypertable for TimescaleDB
SELECT create_hypertable('failure_events', 'timestamp', if_not_exists => TRUE);

-- Patterns table (updated via analysis pipeline)
CREATE TABLE failure_patterns (
    pattern_id UUID PRIMARY KEY,
    failure_type VARCHAR(50) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    failure_count BIGINT,
    first_seen TIMESTAMPTZ,
    last_seen TIMESTAMPTZ,
    suggested_remediation TEXT,
    
    UNIQUE(failure_type, model_name)
);

-- Prompt versions (immutable log)
CREATE TABLE prompt_versions (
    version_id UUID PRIMARY KEY,
    model_name VARCHAR(100) NOT NULL,
    prompt_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    deployed_at TIMESTAMPTZ,
    success_rate FLOAT,
    
    UNIQUE(model_name, prompt_hash)
);

-- Correlations (materialized analysis results)
CREATE TABLE failure_correlations (
    correlation_id UUID PRIMARY KEY,
    factor_a VARCHAR(255),
    factor_b VARCHAR(255),
    correlation_strength FLOAT,
    failure_count_both INTEGER,
    chi_squared FLOAT,
    p_value FLOAT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- User feedback (validation of classifications)
CREATE TABLE failure_feedback (
    feedback_id UUID PRIMARY KEY,
    event_id UUID NOT NULL REFERENCES failure_events(event_id),
    user_id VARCHAR(100),
    is_actual_failure BOOLEAN,
    corrected_failure_type VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Indexes for Performance

```sql
-- Time-range queries (most common)
CREATE INDEX idx_events_time_type ON failure_events (timestamp DESC, failure_type);

-- By model performance
CREATE INDEX idx_events_model ON failure_events (model_name, timestamp DESC);

-- By environment
CREATE INDEX idx_events_env ON failure_events (environment, timestamp DESC);

-- Full-text search on prompts (if storing full text)
CREATE INDEX idx_prompt_text ON failure_events USING GIN(to_tsvector('english', prompt));

-- Compression for older data
ALTER TABLE failure_events SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'timestamp DESC'
);

SELECT add_compression_policy('failure_events', INTERVAL '30 days');
```

---

## API Request/Response Models

### POST /events (Ingest Failures)

**Request:**
```json
{
    "events": [
        {
            "timestamp": "2026-04-29T10:30:00Z",
            "model_name": "gpt-4",
            "prompt": "...",
            "response": "...",
            "failure_type": "hallucination",
            "confidence_score": 0.95,
            "metadata": {
                "user_id": "user123",
                "session_id": "sess456"
            }
        }
    ]
}
```

**Response (202 Accepted):**
```json
{
    "status": "received",
    "event_count": 1,
    "batch_id": "batch_xyz"
}
```

### GET /failures?type=hallucination&hours=24

**Response:**
```json
{
    "failures": [
        {
            "event_id": "evt_123",
            "timestamp": "2026-04-29T10:30:00Z",
            "model": "gpt-4",
            "failure_type": "hallucination",
            "prompt": "What is...",
            "confidence_score": 0.95,
            "severity": "high"
        }
    ],
    "total_count": 45,
    "page": 1,
    "per_page": 10
}
```

### GET /patterns

**Response:**
```json
{
    "patterns": [
        {
            "pattern_id": "pat_abc",
            "failure_type": "hallucination",
            "model_name": "gpt-4",
            "occurrence_count": 127,
            "last_seen": "2026-04-29T14:22:00Z",
            "suggested_remediation": "Improve context window with recent docs",
            "affected_users": 23
        }
    ]
}
```

---

## Constraints & Validation Rules

1. **Data Retention**: Raw failure events retained 90 days; patterns/aggregates 1 year
2. **Null Handling**: Optional fields default to NULL; no synthetic "unknown" strings
3. **Timestamps**: Always UTC, ISO 8601 format
4. **Uniqueness**: event_id is globally unique (UUIDv4)
5. **Immutability**: Once logged, events cannot be modified (append-only)
6. **PII Protection**: User data redacted/hashed in non-production environments
7. **Validation**: 
   - confidence_score: 0.0 - 1.0 (fail if outside)
   - latency_ms: >= 0
   - response_length: > 0 (or explicitly 0 for empty responses)
   - failure_type: must be valid enum value

---

## Migration Strategy

```sql
-- Version 1.0 (MVP)
-- Create initial tables above

-- Version 1.1 (Add Feedback)
ALTER TABLE failure_events ADD COLUMN is_confirmed_failure BOOLEAN DEFAULT FALSE;
CREATE TABLE failure_feedback (...);

-- Version 1.2 (Performance Tuning)
CREATE INDEX idx_events_model ON failure_events (model_name, timestamp DESC);
SELECT add_compression_policy('failure_events', INTERVAL '30 days');
```

Use **Alembic** (Python) or **Flyway** (Java/SQL) for migration management.

---

## Example Queries (For Analysis Layer)

```sql
-- Top failure patterns this week
SELECT failure_type, COUNT(*) as count
FROM failure_events
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY failure_type
ORDER BY count DESC;

-- Models with highest failure rate
SELECT 
    model_name, 
    COUNT(*) as total_calls,
    SUM(CASE WHEN failure_type != 'NONE' THEN 1 ELSE 0 END) as failures,
    (failures::float / total_calls) as failure_rate
FROM failure_events
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY model_name
ORDER BY failure_rate DESC;

-- Retrieval quality correlation with failures
SELECT 
    CASE WHEN retrieval_score > 0.8 THEN 'good'
         WHEN retrieval_score > 0.5 THEN 'fair'
         ELSE 'poor' END as retrieval_quality,
    COUNT(*) as event_count,
    AVG(confidence_score) as avg_confidence
FROM failure_events
WHERE failure_type = 'hallucination'
GROUP BY retrieval_quality;
```
