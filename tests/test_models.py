from datetime import UTC, datetime
from decimal import Decimal
import unittest
from uuid import uuid4

from pydantic import ValidationError

from src.models import (
    AuditEvent,
    Domain,
    PostcheckResponse,
    PrecheckResponse,
    ProcessingDecision,
    RiskLevel,
    SecurityRequest,
    ValidationStatus,
)


class TestModels(unittest.TestCase):
    def test_security_request_accepts_valid_payload(self) -> None:
        request = SecurityRequest(
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            query="Summarize this lab result.",
            domain=Domain.LAB_INTERPRETATION,
            metadata={"urgency": "routine"},
        )

        self.assertEqual(request.domain, Domain.LAB_INTERPRETATION)
        self.assertEqual(request.metadata, {"urgency": "routine"})

    def test_security_request_rejects_empty_query(self) -> None:
        with self.assertRaises(ValidationError):
            SecurityRequest(
                request_id=uuid4(),
                session_id=uuid4(),
                user_id=uuid4(),
                query="",
                domain=Domain.CLINICAL_SUMMARY,
            )

    def test_security_request_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            SecurityRequest(
                request_id=uuid4(),
                session_id=uuid4(),
                user_id=uuid4(),
                query="Check for drug interactions.",
                domain=Domain.DRUG_INTERACTION,
                raw_phi="not allowed",
            )

    def test_precheck_response_accepts_valid_payload(self) -> None:
        response = PrecheckResponse(
            sanitized_query="Review [PHI_NAME_001]'s lab trend.",
            risk_level=RiskLevel.MEDIUM,
            decision=ProcessingDecision.ALLOW,
            entity_count=1,
            entity_types=["PERSON"],
            requires_llm=True,
        )

        self.assertIsNone(response.blocked_reason)
        self.assertTrue(response.requires_llm)

    def test_precheck_response_rejects_negative_entity_count(self) -> None:
        with self.assertRaises(ValidationError):
            PrecheckResponse(
                sanitized_query="Clean query.",
                risk_level=RiskLevel.LOW,
                decision=ProcessingDecision.ALLOW,
                entity_count=-1,
                entity_types=[],
                requires_llm=True,
            )

    def test_postcheck_response_accepts_valid_payload(self) -> None:
        response = PostcheckResponse(
            answer="No urgent abnormality was identified.",
            confidence_score=0.82,
            risk_level=RiskLevel.LOW,
            validation_status=ValidationStatus.PASSED,
            sources=["lab_panel"],
            requires_human_review=False,
        )

        self.assertEqual(response.validation_status, ValidationStatus.PASSED)
        self.assertFalse(response.requires_human_review)

    def test_postcheck_response_rejects_confidence_above_one(self) -> None:
        with self.assertRaises(ValidationError):
            PostcheckResponse(
                answer="Review required.",
                confidence_score=1.5,
                risk_level=RiskLevel.HIGH,
                validation_status=ValidationStatus.FAILED,
                sources=[],
                requires_human_review=True,
            )

    def test_audit_event_accepts_phi_free_lifecycle_fields(self) -> None:
        event = AuditEvent(
            request_id=uuid4(),
            session_id=uuid4(),
            timestamp=datetime.now(UTC),
            user_id=uuid4(),
            domain=Domain.RADIOLOGY_SUMMARY,
            risk_level=RiskLevel.HIGH,
            decision=ProcessingDecision.ALLOW,
            model_used="claude-opus-4-7",
            prompt_version="healthcare-safe-high-v1",
            tokens_used=1280,
            cost=Decimal("0.42"),
            validation_status=ValidationStatus.SANITIZED,
            confidence_score=0.74,
        )

        self.assertEqual(event.tokens_used, 1280)
        self.assertEqual(event.cost, Decimal("0.42"))

    def test_audit_event_rejects_negative_cost(self) -> None:
        with self.assertRaises(ValidationError):
            AuditEvent(
                request_id=uuid4(),
                session_id=uuid4(),
                timestamp=datetime.now(UTC),
                user_id=uuid4(),
                domain=Domain.DISCHARGE_NOTE,
                risk_level=RiskLevel.CRITICAL,
                decision=ProcessingDecision.HUMAN_REVIEW,
                tokens_used=0,
                cost=Decimal("-0.01"),
                validation_status=ValidationStatus.BLOCKED,
                confidence_score=0.0,
            )

    def test_enums_parse_from_wire_values(self) -> None:
        request = SecurityRequest(
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            query="Review discharge instructions.",
            domain="discharge_note",
        )

        self.assertEqual(request.domain, Domain.DISCHARGE_NOTE)


if __name__ == "__main__":
    unittest.main()
