"""Response models for security pipeline checkpoints."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(StrEnum):
    """Deterministic risk bands used before model routing."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ValidationStatus(StrEnum):
    """Output validation outcomes for model responses."""

    PASSED = "PASSED"
    SANITIZED = "SANITIZED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ProcessingDecision(StrEnum):
    """Pipeline decision made after security checks."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class PrecheckResponse(BaseModel):
    """Response from pre-LLM security checks."""

    model_config = ConfigDict(extra="forbid")

    sanitized_query: str
    risk_level: RiskLevel
    decision: ProcessingDecision
    blocked_reason: str | None = None
    entity_count: int = Field(ge=0)
    entity_types: list[str] = Field(default_factory=list)
    requires_llm: bool


class PostcheckResponse(BaseModel):
    """Response from post-LLM output validation."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    validation_status: ValidationStatus
    sources: list[str] = Field(default_factory=list)
    requires_human_review: bool
