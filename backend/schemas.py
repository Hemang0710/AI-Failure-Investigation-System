"""Pydantic request/response schemas."""

from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional, List, Dict, Any
from models import FailureTypeEnum, SeverityEnum


# ============ Event Ingestion ============

class FailureEventCreate(BaseModel):
    """Event submission from SDK."""
    timestamp: datetime
    model_name: str
    provider: Optional[str] = None
    prompt: str
    response: str
    response_length: Optional[int] = None
    latency_ms: Optional[int] = None
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    failure_type: FailureTypeEnum
    failure_severity: Optional[SeverityEnum] = None
    retrieval_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    retrieval_results: Optional[List[str]] = None
    context_relevance: Optional[float] = Field(None, ge=0.0, le=1.0)
    environment: Optional[str] = "production"
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("confidence_score", "retrieval_score", "context_relevance")
    def validate_score(cls, v):
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError("Score must be between 0.0 and 1.0")
        return v


class BatchEventIngestion(BaseModel):
    """Batch event submission."""
    events: List[FailureEventCreate]

    @field_validator("events")
    def validate_batch_size(cls, v):
        if len(v) > 1000:
            raise ValueError("Batch size exceeds maximum of 1000 events")
        return v


class EventIngestionResponse(BaseModel):
    """Response to event ingestion."""
    status: str
    event_count: int
    batch_id: str
    timestamp: datetime


# ============ Failure Queries ============

class FailureEventResponse(BaseModel):
    """Single failure event response."""
    event_id: str
    timestamp: datetime
    model_name: str
    failure_type: FailureTypeEnum
    failure_severity: Optional[SeverityEnum]
    prompt: str
    response: str
    confidence_score: Optional[float]
    retrieval_score: Optional[float]
    latency_ms: Optional[int]
    user_id: Optional[str]
    environment: Optional[str]

    class Config:
        from_attributes = True


class FailureDetailResponse(FailureEventResponse):
    """Detailed failure event with all metadata."""
    model_version: Optional[str]
    provider: Optional[str]
    system_instructions: Optional[str]
    response_length: Optional[int]
    retrieval_results: Optional[List[str]]
    context_relevance: Optional[float]
    semantic_coherence: Optional[float]
    factual_accuracy: Optional[float]
    session_id: Optional[str]
    tags: Optional[List[str]]
    metadata: Optional[Dict[str, Any]]


class PaginationInfo(BaseModel):
    """Pagination metadata."""
    total_count: int
    page: int
    limit: int
    total_pages: int


class FailuresQueryResponse(BaseModel):
    """Response to failure list query."""
    failures: List[FailureEventResponse]
    pagination: PaginationInfo
    filters_applied: Dict[str, Any]


# ============ Pattern Detection ============

class PatternResponse(BaseModel):
    """Detected failure pattern."""
    pattern_id: str
    failure_type: FailureTypeEnum
    model_name: Optional[str]
    occurrence_count: int
    unique_users_affected: int
    first_seen: datetime
    last_seen: datetime
    average_confidence: Optional[float]
    average_latency_ms: Optional[float]
    average_retrieval_score: Optional[float]
    suggested_remediation: Optional[str]
    remediation_tested: bool
    remediation_effectiveness: Optional[float]
    severity_breakdown: Dict[str, int]

    class Config:
        from_attributes = True


class PatternsSummary(BaseModel):
    """Summary of pattern statistics."""
    total_patterns: int
    patterns_with_remediation: int
    avg_occurrences_per_pattern: float


class PatternsQueryResponse(BaseModel):
    """Response to pattern list query."""
    patterns: List[PatternResponse]
    summary: PatternsSummary


class PatternFeedbackCreate(BaseModel):
    """Feedback on pattern remediation."""
    remediation_tested: bool
    remediation_effectiveness: Optional[float] = Field(None, ge=0.0, le=1.0)
    implementation_notes: Optional[str] = None
    new_prompt_version_id: Optional[str] = None


class PatternFeedbackResponse(BaseModel):
    """Response to pattern feedback submission."""
    feedback_id: str
    pattern_id: str
    timestamp: datetime
    status: str


# ============ User Feedback ============

class UserFeedbackCreate(BaseModel):
    """User validation of failure classification."""
    event_id: str
    is_actual_failure: bool
    corrected_failure_type: Optional[FailureTypeEnum] = None
    notes: Optional[str] = None
    user_id: Optional[str] = None


class UserFeedbackResponse(BaseModel):
    """Response to user feedback."""
    feedback_id: str
    event_id: str
    timestamp: datetime
    status: str


# ============ Model Performance ============

class ModelStats(BaseModel):
    """Per-model performance statistics."""
    model_name: str
    total_events: int
    failure_count: int
    failure_rate: float
    average_confidence: Optional[float]
    average_latency_ms: Optional[float]
    distinct_failure_types: int
    severity_breakdown: Dict[str, int]

    class Config:
        from_attributes = True


class TimePeriod(BaseModel):
    """Time period information."""
    start: datetime
    end: datetime
    hours: int


class ModelsQueryResponse(BaseModel):
    """Response to model performance query."""
    models: List[ModelStats]
    period: TimePeriod


# ============ System Statistics ============

class SystemStats(BaseModel):
    """Aggregate system-wide statistics."""
    time_period: TimePeriod
    total_events: int
    total_failures: int
    overall_failure_rate: float
    failure_type_distribution: Dict[str, int]
    severity_distribution: Dict[str, int]
    average_confidence_when_fails: Optional[float]
    model_with_highest_failures: Optional[str]
    failure_rate_trend: str  # stable, increasing, decreasing
    active_patterns: int
    patterns_with_remediation: int


# ============ Errors ============

class ErrorDetail(BaseModel):
    """Error detail information."""
    field: Optional[str] = None
    reason: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    code: str
    message: str
    details: Optional[ErrorDetail] = None
    timestamp: datetime
    request_id: Optional[str] = None


class RateLimitError(BaseModel):
    """Rate limit error response."""
    code: str = "rate_limited"
    message: str
    retry_after: int


# ============ Health ============

class ComponentStatus(BaseModel):
    """Status of a system component."""
    name: str
    status: str  # healthy, degraded, unhealthy


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: datetime
    components: Dict[str, str]  # component_name -> status
