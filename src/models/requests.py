"""Request models for the AI security control plane."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Domain(StrEnum):
    """Clinical domains supported by the control plane."""

    LAB_INTERPRETATION = "lab_interpretation"
    RADIOLOGY_SUMMARY = "radiology_summary"
    CLINICAL_SUMMARY = "clinical_summary"
    DRUG_INTERACTION = "drug_interaction"
    DISCHARGE_NOTE = "discharge_note"


class Role(StrEnum):
    """User roles supported by deterministic access policy."""

    PATIENT = "patient"
    LAB_TECH = "lab_tech"
    PHYSICIAN = "physician"
    ADMIN = "admin"


class SecurityRequest(BaseModel):
    """Inbound request contract before security pipeline processing."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    session_id: UUID
    user_id: UUID
    query: str = Field(min_length=1, max_length=2000)
    domain: Domain
    role: Role = Role.PATIENT
    metadata: dict[str, Any] | None = None
