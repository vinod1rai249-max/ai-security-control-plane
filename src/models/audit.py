"""Audit event models for immutable request lifecycle records."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.requests import Domain
from src.models.responses import ProcessingDecision, RiskLevel, ValidationStatus


class AuditEvent(BaseModel):
    """PHI-free audit record produced for every request lifecycle."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    session_id: UUID
    timestamp: datetime | None = None
    timestamp_utc: datetime | None = None
    user_id: UUID
    domain: Domain
    risk_level: RiskLevel
    decision: ProcessingDecision
    query_hash: str = ""
    use_llm: bool = False
    selected_model: str = "none"
    audit_id: str | None = None
    model_used: str | None = None
    prompt_version: str | None = None
    tokens_used: int = Field(ge=0)
    cost: Decimal = Field(ge=Decimal("0"))
    validation_status: ValidationStatus
    confidence_score: float = Field(ge=0.0, le=1.0)
