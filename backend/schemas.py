"""Pydantic request/response schemas."""

from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional, List, Dict, Any
from models import FailureTypeEnum, SeverityEnum, TaskTypeEnum


# ============ Event Ingestion ============

# Upper bound for prompt/response text; keeps a single event from filling storage
MAX_TEXT_LENGTH = 100_000
MAX_METADATA_CHARS = 50_000


class FailureEventCreate(BaseModel):
    """Event submission from SDK.

    ``failure_type`` is optional: an event without one records a *successful*
    call. Reporting (a sample of) successes is what makes per-model and
    per-task success rates trustworthy rather than failure-only counts.
    """
    timestamp: datetime
    model_name: str = Field(min_length=1, max_length=255)
    provider: Optional[str] = Field(None, max_length=100)
    prompt: str = Field(max_length=MAX_TEXT_LENGTH)
    response: str = Field(max_length=MAX_TEXT_LENGTH)
    response_length: Optional[int] = Field(None, ge=0)
    latency_ms: Optional[int] = Field(None, ge=0)
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    failure_type: Optional[FailureTypeEnum] = None
    failure_severity: Optional[SeverityEnum] = None
    task_type: Optional[TaskTypeEnum] = None
    input_tokens: Optional[int] = Field(None, ge=0)
    output_tokens: Optional[int] = Field(None, ge=0)
    cost_usd: Optional[float] = Field(None, ge=0.0)
    retrieval_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    retrieval_results: Optional[List[str]] = Field(None, max_length=100)
    context_relevance: Optional[float] = Field(None, ge=0.0, le=1.0)
    environment: Optional[str] = Field("production", max_length=100)
    session_id: Optional[str] = Field(None, max_length=255)
    user_id: Optional[str] = Field(None, max_length=255)
    tags: Optional[List[str]] = Field(None, max_length=50)
    event_metadata: Optional[Dict[str, Any]] = None

    @field_validator("confidence_score", "retrieval_score", "context_relevance")
    def validate_score(cls, v):
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError("Score must be between 0.0 and 1.0")
        return v

    @field_validator("tags", "retrieval_results")
    def validate_item_length(cls, v):
        if v is not None and any(len(item) > 1000 for item in v):
            raise ValueError("List items must be 1000 characters or fewer")
        return v

    @field_validator("event_metadata")
    def validate_metadata_size(cls, v):
        if v is not None:
            import json
            if len(json.dumps(v, default=str)) > MAX_METADATA_CHARS:
                raise ValueError(
                    f"event_metadata exceeds maximum of {MAX_METADATA_CHARS} characters when serialized"
                )
        return v


class BatchEventIngestion(BaseModel):
    """Batch event submission."""
    events: List[FailureEventCreate] = Field(min_length=1, max_length=1000)


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
    # Nullable in the DB (rows can be created outside the API), so the
    # response must tolerate missing text rather than 500 on the whole page.
    prompt: Optional[str]
    response: Optional[str]
    confidence_score: Optional[float]
    retrieval_score: Optional[float]
    latency_ms: Optional[int]
    user_id: Optional[int]
    environment: Optional[str]
    task_type: Optional[TaskTypeEnum] = None

    class Config:
        from_attributes = True


class FailureDetailResponse(FailureEventResponse):
    """Detailed failure event with all metadata."""
    model_version: Optional[str]
    provider: Optional[str]
    system_instructions: Optional[str]
    response_length: Optional[int]
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    retrieval_results: Optional[List[str]]
    context_relevance: Optional[float]
    semantic_coherence: Optional[float]
    factual_accuracy: Optional[float]
    session_id: Optional[str]
    tags: Optional[List[str]]
    event_metadata: Optional[Dict[str, Any]]


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
    implementation_notes: Optional[str] = Field(None, max_length=10_000)
    new_prompt_version_id: Optional[str] = Field(None, max_length=255)


class PatternFeedbackResponse(BaseModel):
    """Response to pattern feedback submission."""
    feedback_id: str
    pattern_id: str
    timestamp: datetime
    status: str


# ============ User Feedback ============

class UserFeedbackCreate(BaseModel):
    """User validation of failure classification."""
    event_id: str = Field(min_length=1, max_length=255)
    is_actual_failure: bool
    corrected_failure_type: Optional[FailureTypeEnum] = None
    notes: Optional[str] = Field(None, max_length=10_000)
    user_id: Optional[str] = Field(None, max_length=255)


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
    average_cost_usd: Optional[float] = None
    total_cost_usd: Optional[float] = None

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


# ============ Model Recommendations (task fit) ============

class TaskModelStats(BaseModel):
    """How one model performs on one task type."""
    model_name: str
    provider: Optional[str]
    total_events: int
    failure_count: int
    failure_rate: float
    success_rate: float
    average_latency_ms: Optional[float]
    average_cost_usd: Optional[float]
    top_failure_type: Optional[str]
    sample_sufficient: bool


class TaskRecommendation(BaseModel):
    """Ranked model list for one task type."""
    task_type: TaskTypeEnum
    total_events: int
    ranked_models: List[TaskModelStats]
    recommended_model: Optional[str]
    caveat: Optional[str]


class RecommendationsResponse(BaseModel):
    """Response to model recommendation query.

    Rankings reflect *observed reliability on this workload*, not benchmark
    scores; the caveats matter when samples are small.
    """
    period: TimePeriod
    min_events: int
    tasks: List[TaskRecommendation]


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


# ============ Correlations ============

class CorrelationItem(BaseModel):
    """Statistical correlation between two factors."""
    correlation_id: str
    factor_a: str
    factor_b: str
    correlation_strength: float  # 0-1, phi coefficient absolute value
    chi_squared: Optional[float] = None
    p_value: Optional[float] = None
    is_significant: bool
    interpretation: str


class CorrelationsResponse(BaseModel):
    """Response to correlation analysis query."""
    correlations: List[CorrelationItem]
    computed_at: datetime
    events_analyzed: int
