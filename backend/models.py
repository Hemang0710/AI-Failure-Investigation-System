"""SQLAlchemy ORM models for the failure investigation system."""

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, JSON, Enum, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from database import Base


class FailureTypeEnum(str, enum.Enum):
    """Supported failure types."""
    HALLUCINATION = "hallucination"
    EMPTY_RESPONSE = "empty_response"
    MALFORMED_RESPONSE = "malformed_response"
    TIMEOUT = "timeout"
    SEMANTIC_ERROR = "semantic_error"
    CONFIDENCE_MISMATCH = "confidence_mismatch"
    RETRIEVAL_FAILURE = "retrieval_failure"
    RATE_LIMITED = "rate_limited"
    TOKEN_LIMIT = "token_limit"


class SeverityEnum(str, enum.Enum):
    """Failure severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class User(Base):
    """User account for API access."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True)
    email = Column(String(255), unique=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    api_keys = relationship("APIKey", back_populates="user")
    events = relationship("FailureEvent", back_populates="user")
    feedback = relationship("Feedback", back_populates="user")


class APIKey(Base):
    """API key for authentication."""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key_hash = Column(String(255), unique=True, index=True)
    name = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="api_keys")


class FailureEvent(Base):
    """A single failure event from an LLM call."""
    __tablename__ = "failure_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(255), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Timing
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    latency_ms = Column(Integer)

    # LLM Identification
    model_name = Column(String(255), nullable=False, index=True)
    model_version = Column(String(255))
    provider = Column(String(100), index=True)  # openai, anthropic, etc

    # Input
    prompt = Column(Text)
    system_instructions = Column(Text, nullable=True)

    # Output
    response = Column(Text)
    response_length = Column(Integer)
    confidence_score = Column(Float)

    # Failure Classification
    failure_type = Column(Enum(FailureTypeEnum), nullable=False, index=True)
    failure_severity = Column(Enum(SeverityEnum), index=True)

    # Retrieval Metrics
    retrieval_score = Column(Float, nullable=True)
    retrieval_results = Column(JSON, nullable=True)
    context_relevance = Column(Float, nullable=True)

    # Quality Metrics
    semantic_coherence = Column(Float, nullable=True)
    factual_accuracy = Column(Float, nullable=True)

    # Context
    environment = Column(String(100), index=True)  # production, staging, dev
    session_id = Column(String(255), index=True)
    tags = Column(JSON, nullable=True)
    event_metadata = Column(JSON, nullable=True)

    # Pattern Matching
    pattern_id = Column(Integer, ForeignKey("patterns.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="events")
    pattern = relationship("Pattern", back_populates="events")
    feedback = relationship("Feedback", back_populates="event")

    __table_args__ = (
        Index("ix_timestamp_model", timestamp, model_name),
        Index("ix_timestamp_type", timestamp, failure_type),
        Index("ix_session_user", session_id, user_id),
    )


class Pattern(Base):
    """Detected recurring failure pattern."""
    __tablename__ = "patterns"

    id = Column(Integer, primary_key=True, index=True)
    pattern_id = Column(String(255), unique=True, index=True)

    # Pattern Characteristics
    failure_type = Column(Enum(FailureTypeEnum), nullable=False, index=True)
    model_name = Column(String(255), index=True)

    # Occurrence Statistics
    occurrence_count = Column(Integer, default=0)
    unique_users_affected = Column(Integer, default=0)
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)

    # Quality Metrics
    average_confidence = Column(Float)
    average_latency_ms = Column(Float)
    average_retrieval_score = Column(Float)

    # Remediation
    suggested_remediation = Column(Text, nullable=True)
    remediation_tested = Column(Boolean, default=False)
    remediation_effectiveness = Column(Float, nullable=True)

    # Severity Breakdown (JSON for flexibility)
    severity_breakdown = Column(JSON, default={
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0
    })

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    events = relationship("FailureEvent", back_populates="pattern")
    feedback = relationship("PatternFeedback", back_populates="pattern")


class PatternFeedback(Base):
    """User feedback on pattern remediation."""
    __tablename__ = "pattern_feedback"

    id = Column(Integer, primary_key=True, index=True)
    pattern_id = Column(Integer, ForeignKey("patterns.id"), nullable=False)

    remediation_tested = Column(Boolean)
    remediation_effectiveness = Column(Float, nullable=True)
    implementation_notes = Column(Text, nullable=True)
    new_prompt_version_id = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    pattern = relationship("Pattern", back_populates="feedback")


class Feedback(Base):
    """User validation of failure classification."""
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    feedback_id = Column(String(255), unique=True, index=True)
    event_id = Column(Integer, ForeignKey("failure_events.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    is_actual_failure = Column(Boolean)
    corrected_failure_type = Column(Enum(FailureTypeEnum), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    event = relationship("FailureEvent", back_populates="feedback")
    user = relationship("User", back_populates="feedback")
