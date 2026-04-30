# API Specification

Complete REST API specification for the AI Failure Investigation System. Use this as the blueprint for generating FastAPI endpoints with Claude.

---

## Overview

- **Base URL**: `/api/v1`
- **Authentication**: Bearer token (JWT) in Authorization header
- **Rate Limiting**: 1000 req/min per API key
- **Response Format**: JSON
- **Errors**: HTTP status codes + error object

---

## Authentication

**Request Header:**
```
Authorization: Bearer YOUR_API_KEY
```

**Error Response (401):**
```json
{
    "error": {
        "code": "unauthorized",
        "message": "Invalid or missing API key"
    }
}
```

---

## Endpoints

### 1. POST /events - Ingest Failure Events

**Purpose**: Accept batch failure event submissions from SDKs or integrations.

**Request:**
```http
POST /api/v1/events
Authorization: Bearer token
Content-Type: application/json

{
    "events": [
        {
            "timestamp": "2026-04-29T10:30:00Z",
            "model_name": "gpt-4",
            "provider": "openai",
            "prompt": "What is the capital of France?",
            "response": "The capital of France is London.",
            "response_length": 42,
            "latency_ms": 245,
            "confidence_score": 0.92,
            "failure_type": "hallucination",
            "failure_severity": "high",
            "retrieval_score": 0.87,
            "environment": "production",
            "session_id": "sess_abc123",
            "user_id": "user_456",
            "tags": ["france-geography", "test-session"],
            "metadata": {
                "request_id": "req_789",
                "version": "1.0"
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
    "batch_id": "batch_xyz789",
    "timestamp": "2026-04-29T10:30:15Z"
}
```

**Error Responses:**
- `400 Bad Request`: Malformed JSON or invalid event schema
- `413 Payload Too Large`: Batch exceeds 1000 events or 5MB
- `429 Too Many Requests`: Rate limited

**Validation Rules:**
- Max 1000 events per batch
- Max 5MB payload size
- `timestamp`: ISO 8601, required
- `model_name`: Required, max 100 chars
- `failure_type`: Must be valid enum value
- `confidence_score`: 0.0 - 1.0 if provided
- `latency_ms`: >= 0

---

### 2. GET /failures - Query Failures

**Purpose**: Retrieve failure events with filtering, pagination, and sorting.

**Request:**
```http
GET /api/v1/failures?type=hallucination&model=gpt-4&hours=24&severity=high&page=1&limit=20&sort=timestamp
Authorization: Bearer token
```

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | - | Failure type filter (enum value) |
| `model` | string | - | Filter by model name |
| `hours` | integer | 24 | Look back N hours (max 720) |
| `severity` | string | - | Filter by severity (critical/high/medium/low) |
| `environment` | string | - | Filter by environment (production/staging/dev) |
| `session_id` | string | - | Filter by session |
| `user_id` | string | - | Filter by user |
| `search` | string | - | Full-text search in prompt/response |
| `page` | integer | 1 | Pagination page (1-indexed) |
| `limit` | integer | 20 | Results per page (1-100) |
| `sort` | string | `-timestamp` | Sort field: timestamp, confidence_score, latency_ms |

**Response (200 OK):**
```json
{
    "failures": [
        {
            "event_id": "evt_abc123",
            "timestamp": "2026-04-29T10:30:00Z",
            "model_name": "gpt-4",
            "failure_type": "hallucination",
            "failure_severity": "high",
            "prompt": "What is the capital of France?",
            "response": "The capital of France is London.",
            "confidence_score": 0.92,
            "retrieval_score": 0.87,
            "latency_ms": 245,
            "user_id": "user_456",
            "environment": "production"
        }
    ],
    "pagination": {
        "total_count": 456,
        "page": 1,
        "limit": 20,
        "total_pages": 23
    },
    "filters_applied": {
        "type": "hallucination",
        "model": "gpt-4",
        "hours": 24,
        "severity": "high"
    }
}
```

**Error Responses:**
- `400 Bad Request`: Invalid query parameters
- `404 Not Found`: Requested page beyond available results

---

### 3. GET /failures/:event_id - Get Single Failure

**Purpose**: Retrieve detailed information about a specific failure event.

**Request:**
```http
GET /api/v1/failures/evt_abc123
Authorization: Bearer token
```

**Response (200 OK):**
```json
{
    "event_id": "evt_abc123",
    "timestamp": "2026-04-29T10:30:00Z",
    "model_name": "gpt-4",
    "model_version": "v1.2.3",
    "provider": "openai",
    
    "prompt": "What is the capital of France?",
    "system_instructions": "You are a geography expert.",
    "response": "The capital of France is London.",
    
    "confidence_score": 0.92,
    "latency_ms": 245,
    "failure_type": "hallucination",
    "failure_severity": "high",
    
    "retrieval_score": 0.87,
    "retrieval_results": [
        "France capital: Paris (90% match)",
        "History of Paris (45% match)"
    ],
    "context_relevance": 0.91,
    
    "semantic_coherence": 0.88,
    "factual_accuracy": 0.15,
    
    "environment": "production",
    "session_id": "sess_abc123",
    "user_id": "user_456",
    "tags": ["france-geography"],
    "metadata": {
        "request_id": "req_789",
        "version": "1.0"
    },
    
    "is_confirmed_failure": true,
    "feedback": {
        "feedback_id": "fb_xyz",
        "is_actual_failure": true,
        "corrected_failure_type": "hallucination",
        "notes": "Model incorrectly asserted London is capital of France",
        "created_at": "2026-04-29T10:35:00Z"
    },
    
    "matching_patterns": [
        {
            "pattern_id": "pat_123",
            "failure_type": "hallucination",
            "occurrence_count": 127
        }
    ]
}
```

**Error Responses:**
- `404 Not Found`: Event ID doesn't exist

---

### 4. GET /patterns - Get Failure Patterns

**Purpose**: Retrieve recurring failure patterns with aggregated statistics.

**Request:**
```http
GET /api/v1/patterns?model=gpt-4&type=hallucination&limit=20&sort=occurrence_count
Authorization: Bearer token
```

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | - | Filter by model name |
| `type` | string | - | Failure type filter |
| `limit` | integer | 20 | Results per page (1-100) |
| `sort` | string | `-occurrence_count` | Sort: occurrence_count, last_seen, severity |

**Response (200 OK):**
```json
{
    "patterns": [
        {
            "pattern_id": "pat_abc123",
            "failure_type": "hallucination",
            "model_name": "gpt-4",
            "occurrence_count": 127,
            "unique_users_affected": 23,
            "first_seen": "2026-04-15T08:00:00Z",
            "last_seen": "2026-04-29T14:22:00Z",
            
            "average_confidence": 0.89,
            "average_latency_ms": 243,
            "average_retrieval_score": 0.72,
            
            "suggested_remediation": "Improve context window with recent documentation",
            "remediation_tested": false,
            
            "severity_breakdown": {
                "critical": 5,
                "high": 87,
                "medium": 35,
                "low": 0
            }
        }
    ],
    "summary": {
        "total_patterns": 45,
        "patterns_with_remediation": 12,
        "avg_occurrences_per_pattern": 34.2
    }
}
```

---

### 5. POST /patterns/:pattern_id/feedback - Log Pattern Feedback

**Purpose**: Record whether a suggested remediation was tested and effective.

**Request:**
```http
POST /api/v1/patterns/pat_abc123/feedback
Authorization: Bearer token
Content-Type: application/json

{
    "remediation_tested": true,
    "remediation_effectiveness": 0.78,
    "implementation_notes": "Expanded context window to 4000 tokens, reduced hallucinations by 22%",
    "new_prompt_version_id": "pv_xyz789"
}
```

**Response (201 Created):**
```json
{
    "feedback_id": "fb_123",
    "pattern_id": "pat_abc123",
    "timestamp": "2026-04-29T14:30:00Z",
    "status": "recorded"
}
```

---

### 6. GET /correlations - Get Failure Correlations

**Purpose**: Discover what factors are correlated with failures.

**Request:**
```http
GET /api/v1/correlations?model=gpt-4&significance_level=0.05&limit=20
Authorization: Bearer token
```

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `model` | string | Filter by model |
| `significance_level` | float | p-value threshold (default 0.05) |
| `limit` | integer | Results per page |

**Response (200 OK):**
```json
{
    "correlations": [
        {
            "correlation_id": "cor_123",
            "factor_a": "model=gpt-4",
            "factor_b": "temperature>1.5",
            "correlation_strength": 0.72,
            "chi_squared": 156.3,
            "p_value": 0.0001,
            "is_significant": true,
            "interpretation": "High temperature strongly associated with failures"
        },
        {
            "correlation_id": "cor_124",
            "factor_a": "retrieval_score<0.5",
            "factor_b": "failure_type=hallucination",
            "correlation_strength": 0.68,
            "chi_squared": 142.1,
            "p_value": 0.0002,
            "is_significant": true
        }
    ]
}
```

---

### 7. GET /models - Get Model Performance Summary

**Purpose**: Get statistics and failure rates per model.

**Request:**
```http
GET /api/v1/models?hours=24
Authorization: Bearer token
```

**Response (200 OK):**
```json
{
    "models": [
        {
            "model_name": "gpt-4",
            "total_events": 5432,
            "failure_count": 189,
            "failure_rate": 0.035,
            "average_confidence": 0.87,
            "average_latency_ms": 245,
            "distinct_failure_types": 6,
            "severity_breakdown": {
                "critical": 2,
                "high": 45,
                "medium": 98,
                "low": 44
            }
        },
        {
            "model_name": "gpt-3.5-turbo",
            "total_events": 12847,
            "failure_count": 456,
            "failure_rate": 0.035,
            "average_confidence": 0.82,
            "average_latency_ms": 180
        }
    ],
    "period": {
        "start": "2026-04-28T14:30:00Z",
        "end": "2026-04-29T14:30:00Z",
        "hours": 24
    }
}
```

---

### 8. POST /feedback - Submit User Feedback on Failure

**Purpose**: Allow users to validate/correct failure classifications.

**Request:**
```http
POST /api/v1/feedback
Authorization: Bearer token
Content-Type: application/json

{
    "event_id": "evt_abc123",
    "is_actual_failure": true,
    "corrected_failure_type": "hallucination",
    "notes": "Model incorrectly asserted a false fact with high confidence",
    "user_id": "user_456"
}
```

**Response (201 Created):**
```json
{
    "feedback_id": "fb_abc123",
    "event_id": "evt_abc123",
    "timestamp": "2026-04-29T14:30:00Z",
    "status": "recorded"
}
```

---

### 9. GET /health - Health Check

**Purpose**: Check API availability and basic system status.

**Request:**
```http
GET /api/v1/health
```

**Response (200 OK):**
```json
{
    "status": "healthy",
    "timestamp": "2026-04-29T14:30:00Z",
    "components": {
        "database": "healthy",
        "event_queue": "healthy",
        "analysis_engine": "healthy"
    }
}
```

---

### 10. GET /stats - System Statistics

**Purpose**: Get aggregate statistics across all failures.

**Request:**
```http
GET /api/v1/stats?hours=24
Authorization: Bearer token
```

**Response (200 OK):**
```json
{
    "time_period": {
        "hours": 24,
        "start": "2026-04-28T14:30:00Z",
        "end": "2026-04-29T14:30:00Z"
    },
    "total_events": 18_279,
    "total_failures": 645,
    "overall_failure_rate": 0.035,
    "failure_type_distribution": {
        "hallucination": 287,
        "empty_response": 156,
        "semantic_error": 98,
        "timeout": 45,
        "other": 59
    },
    "severity_distribution": {
        "critical": 12,
        "high": 234,
        "medium": 312,
        "low": 87
    },
    "average_confidence_when_fails": 0.84,
    "model_with_highest_failures": "gpt-4",
    "failure_rate_trend": "stable",
    "active_patterns": 12,
    "patterns_with_remediation": 5
}
```

---

## Error Handling

**Standard Error Response:**
```json
{
    "error": {
        "code": "invalid_request",
        "message": "Descriptive error message",
        "details": {
            "field": "failure_type",
            "reason": "Must be a valid enum value"
        },
        "timestamp": "2026-04-29T14:30:00Z",
        "request_id": "req_abc123"
    }
}
```

**HTTP Status Codes:**
| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 202 | Accepted (async processing) |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (auth required) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not Found |
| 413 | Payload Too Large |
| 429 | Too Many Requests (rate limited) |
| 500 | Internal Server Error |
| 503 | Service Unavailable |

---

## Rate Limiting

**Headers in Response:**
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 987
X-RateLimit-Reset: 1714418400
```

When rate limited (429):
```json
{
    "error": {
        "code": "rate_limited",
        "message": "Rate limit exceeded",
        "retry_after": 45
    }
}
```

---

## Pagination

**Page-based pagination** for list endpoints:
- Default `limit`: 20
- Max `limit`: 100
- `page`: 1-indexed

**Response includes:**
```json
{
    "pagination": {
        "total_count": 1234,
        "page": 2,
        "limit": 20,
        "total_pages": 62
    }
}
```

---

## Code Generation Prompt

Use this prompt with Claude to generate the FastAPI implementation:

```
Generate a complete FastAPI application implementing this API specification.

Requirements:
1. All endpoints from API-SPECIFICATION.md
2. Request/response validation using Pydantic models
3. Database layer using SQLAlchemy ORM
4. Authentication via Bearer tokens (JWT validation)
5. Proper error handling with consistent error responses
6. Async/await throughout
7. Comprehensive docstrings
8. Type hints on all functions
9. Tests for each endpoint (pytest)

Include:
- main.py (FastAPI app initialization)
- models.py (Pydantic and SQLAlchemy models)
- routers/ (organize by endpoint group)
- database.py (connection management)
- auth.py (JWT validation)
- tests/test_*.py (endpoint tests)
- requirements.txt

Tech stack: FastAPI, SQLAlchemy, PostgreSQL, Pydantic
```
