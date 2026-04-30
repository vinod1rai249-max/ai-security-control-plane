from datetime import UTC, datetime
from decimal import Decimal
import unittest
from uuid import uuid4

from src.models.audit import AuditEvent
from src.models.requests import Domain
from src.models.responses import ProcessingDecision, RiskLevel, ValidationStatus
from src.services.audit_logger import AuditLogger, InMemoryAuditSink


class FailingAuditSink:
    def write(self, audit_id: str, event: AuditEvent) -> None:
        raise RuntimeError("sink unavailable")


class TestAuditLogger(unittest.TestCase):
    def _audit_event(self, **overrides: object) -> AuditEvent:
        data = {
            "request_id": uuid4(),
            "session_id": uuid4(),
            "timestamp": datetime.now(UTC),
            "user_id": uuid4(),
            "domain": Domain.LAB_INTERPRETATION,
            "risk_level": RiskLevel.LOW,
            "decision": ProcessingDecision.ALLOW,
            "model_used": "claude-haiku-4-5-20251001",
            "prompt_version": "healthcare-safe-low-v1",
            "tokens_used": 128,
            "cost": Decimal("0.01"),
            "validation_status": ValidationStatus.PASSED,
            "confidence_score": 0.91,
        }
        data.update(overrides)
        return AuditEvent(**data)

    def test_audit_event_logs_successfully(self) -> None:
        sink = InMemoryAuditSink()
        logger = AuditLogger(sink=sink)
        event = self._audit_event()

        result = logger.log(event)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.audit_id)
        self.assertNotEqual(result.audit_id, "")
        self.assertIsNone(result.error_message)
        self.assertEqual(sink.count(), 1)
        stored_event = sink.get(result.audit_id)
        self.assertEqual(stored_event.request_id, event.request_id)
        self.assertEqual(stored_event.audit_id, result.audit_id)

    def test_audit_event_stores_hash_without_raw_query(self) -> None:
        sink = InMemoryAuditSink()
        logger = AuditLogger(sink=sink)
        event = self._audit_event(query_hash="a" * 64)

        result = logger.log(event)

        self.assertTrue(result.success)
        stored_event = sink.get(result.audit_id)
        self.assertEqual(stored_event.query_hash, "a" * 64)
        self.assertNotIn("query", stored_event.model_dump())

    def test_audit_event_with_phi_like_raw_query_is_rejected(self) -> None:
        sink = InMemoryAuditSink()
        logger = AuditLogger(sink=sink)
        event = self._audit_event(prompt_version="raw query: Patient Jane Doe has MRN 4821901")

        result = logger.log(event)

        self.assertFalse(result.success)
        self.assertIsNone(result.audit_id)
        self.assertIn("PHI-like", result.error_message)
        self.assertEqual(sink.count(), 0)

    def test_audit_failure_returns_success_false(self) -> None:
        logger = AuditLogger(sink=FailingAuditSink())

        result = logger.log(self._audit_event())

        self.assertFalse(result.success)
        self.assertIsNone(result.audit_id)
        self.assertIn("audit write failed", result.error_message)

    def test_no_silent_failure(self) -> None:
        logger = AuditLogger(sink=FailingAuditSink())

        result = logger.log(self._audit_event())

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertNotEqual(result.error_message, "")

    def test_audit_id_is_non_empty(self) -> None:
        logger = AuditLogger()

        result = logger.log(self._audit_event())

        self.assertTrue(result.success)
        self.assertIsInstance(result.audit_id, str)
        self.assertGreater(len(result.audit_id), 0)


if __name__ == "__main__":
    unittest.main()
