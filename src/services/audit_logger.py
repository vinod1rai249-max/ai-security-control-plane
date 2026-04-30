"""Audit logging service with fail-closed write behavior."""

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Protocol
from uuid import uuid4

from src.models.audit import AuditEvent


@dataclass(frozen=True)
class AuditLogResult:
    """Result returned after attempting to write an audit event."""

    success: bool
    audit_id: str | None
    error_message: str | None = None


class AuditSink(Protocol):
    """Storage interface for audit events."""

    def write(self, audit_id: str, event: AuditEvent) -> None:
        """Persist one audit event or raise an exception on failure."""


class InMemoryAuditSink:
    """In-memory audit sink for local development and unit tests."""

    def __init__(self) -> None:
        self._events: dict[str, AuditEvent] = {}

    def write(self, audit_id: str, event: AuditEvent) -> None:
        """Store one event in memory.

        This sink is intentionally simple and temporary. It mirrors the future
        PostgreSQL sink contract by raising on write failure instead of hiding
        errors from the caller.
        """

        if not audit_id:
            raise ValueError("audit_id is required")
        self._events[audit_id] = event

    def get(self, audit_id: str) -> AuditEvent | None:
        """Return an event by audit id for tests and local inspection."""

        return self._events.get(audit_id)

    def count(self) -> int:
        """Return the number of stored audit events."""

        return len(self._events)


class AuditLogger:
    """Writes PHI-free audit events and fails closed on write errors."""

    _PHI_PATTERNS = [
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"),
        re.compile(r"\b(?:MRN|Medical Record(?: Number)?|Medical Record No\.?)\s*[:#-]?\s*[A-Z]{0,3}\d{6,10}\b", re.IGNORECASE),
        re.compile(r"\b(?:Insurance(?: ID| Number)?|Policy(?: ID| Number)?)\s*[:#-]?\s*[A-Z0-9-]{8,16}\b", re.IGNORECASE),
        re.compile(r"\b(?:Patient|Name|Member)\s*(?:Name)?\s*[:#-]?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b"),
        re.compile(r"\braw\s+query\b", re.IGNORECASE),
    ]

    def __init__(self, sink: AuditSink | None = None) -> None:
        self._sink = sink or InMemoryAuditSink()

    def log(self, event: AuditEvent) -> AuditLogResult:
        """Write one audit event or return an explicit failure result.

        Security contract: this method accepts only the PHI-free AuditEvent
        model, performs a defensive PHI-like string check before writing, and
        returns success=False on validation or sink failure. Callers must treat
        a failed result as a stop condition and must not continue silently.
        """

        phi_error = self._validate_no_raw_phi(event)
        if phi_error is not None:
            return AuditLogResult(success=False, audit_id=None, error_message=phi_error)

        audit_id = str(uuid4())
        event_to_write = event.model_copy(
            update={
                "audit_id": audit_id,
                "selected_model": event.selected_model or event.model_used or "none",
            }
        )
        try:
            self._sink.write(audit_id, event_to_write)
        except Exception as exc:
            return AuditLogResult(
                success=False,
                audit_id=None,
                error_message=f"audit write failed: {exc}",
            )

        return AuditLogResult(success=True, audit_id=audit_id)

    def _validate_no_raw_phi(self, event: AuditEvent) -> str | None:
        event_data = event.model_dump(mode="python")
        for field_name, value in event_data.items():
            if self._contains_phi_like_value(value):
                return f"Audit event rejected: field '{field_name}' contains PHI-like text."

        extra_fields = set(event.__dict__) - set(type(event).model_fields)
        if extra_fields:
            return "Audit event rejected: unexpected raw fields are not allowed."

        return None

    def _contains_phi_like_value(self, value: object) -> bool:
        if isinstance(value, str):
            return any(pattern.search(value) for pattern in self._PHI_PATTERNS)

        if isinstance(value, Decimal):
            return False

        if isinstance(value, dict):
            return any(self._contains_phi_like_value(item) for item in value.values())

        if isinstance(value, list | tuple | set):
            return any(self._contains_phi_like_value(item) for item in value)

        return False
