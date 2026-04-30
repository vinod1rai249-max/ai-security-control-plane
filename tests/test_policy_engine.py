import unittest

from src.models.requests import Domain
from src.services.policy_engine import PolicyDecision, PolicyEngine
from src.services.risk_classifier import ClassifiedRiskLevel


class TestPolicyEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PolicyEngine()

    def test_low_risk_lab_explanation_allowed(self) -> None:
        result = self.engine.evaluate(
            sanitized_query="Explain this lab result.",
            risk_level=ClassifiedRiskLevel.LOW,
            flags=["lab_explanation"],
            domain=Domain.LAB_INTERPRETATION,
        )

        self.assertEqual(result.decision, PolicyDecision.ALLOW)
        self.assertIsNone(result.required_disclaimer)
        self.assertEqual(result.policy_flags, ["low_risk_lab_allowed"])

    def test_medium_risk_interpretation_allowed_with_disclaimer(self) -> None:
        result = self.engine.evaluate(
            sanitized_query="Is this value normal?",
            risk_level=ClassifiedRiskLevel.MEDIUM,
            flags=["interpretation_request"],
            domain=Domain.LAB_INTERPRETATION,
        )

        self.assertEqual(result.decision, PolicyDecision.ALLOW_WITH_DISCLAIMER)
        self.assertIsNotNone(result.required_disclaimer)
        self.assertEqual(result.policy_flags, ["disclaimer_required"])

    def test_diagnosis_request_blocked(self) -> None:
        result = self.engine.evaluate(
            sanitized_query="Can you diagnose this symptom pattern?",
            risk_level=ClassifiedRiskLevel.HIGH,
            flags=["diagnosis_intent"],
            domain=Domain.CLINICAL_SUMMARY,
        )

        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertIsNone(result.required_disclaimer)
        self.assertEqual(result.policy_flags, ["diagnosis_intent"])

    def test_medication_request_blocked(self) -> None:
        result = self.engine.evaluate(
            sanitized_query="What medication should be used?",
            risk_level=ClassifiedRiskLevel.HIGH,
            flags=["medication_suggestion"],
            domain=Domain.DRUG_INTERACTION,
        )

        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertEqual(result.policy_flags, ["medication_suggestion"])

    def test_emergency_request_blocked(self) -> None:
        result = self.engine.evaluate(
            sanitized_query="Emergency chest pain and cannot breathe.",
            risk_level=ClassifiedRiskLevel.CRITICAL,
            flags=["emergency_intent"],
            domain=Domain.CLINICAL_SUMMARY,
        )

        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertIn("emergency services", result.reason)
        self.assertEqual(result.policy_flags, ["emergency_intent"])

    def test_unknown_domain_blocked(self) -> None:
        result = self.engine.evaluate(
            sanitized_query="Explain this lab result.",
            risk_level=ClassifiedRiskLevel.LOW,
            flags=["lab_explanation"],
            domain="unknown_domain",
        )

        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertEqual(result.policy_flags, ["unknown_domain"])

    def test_empty_query_blocked(self) -> None:
        result = self.engine.evaluate(
            sanitized_query="   ",
            risk_level=ClassifiedRiskLevel.LOW,
            flags=["lab_explanation"],
            domain=Domain.LAB_INTERPRETATION,
        )

        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertEqual(result.policy_flags, ["empty_query"])

    def test_deterministic_repeated_result(self) -> None:
        kwargs = {
            "sanitized_query": "Is this normal?",
            "risk_level": "medium",
            "flags": ["interpretation_request"],
            "domain": "lab_interpretation",
        }

        first = self.engine.evaluate(**kwargs)
        second = self.engine.evaluate(**kwargs)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
