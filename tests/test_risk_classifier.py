import unittest

from src.services.risk_classifier import ClassifiedRiskLevel, RiskClassifier


class TestRiskClassifier(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = RiskClassifier()

    def test_low_for_general_health_question(self) -> None:
        result = self.classifier.classify("What is a healthy diet for heart health?")

        self.assertEqual(result.risk_level, ClassifiedRiskLevel.LOW)
        self.assertEqual(result.flags, ["general_health_question"])
        self.assertIn("General health", result.reason)

    def test_low_for_lab_explanation(self) -> None:
        result = self.classifier.classify("Please explain this lab result reference range.")

        self.assertEqual(result.risk_level, ClassifiedRiskLevel.LOW)
        self.assertIn("lab_explanation", result.flags)

    def test_medium_for_interpretation_request(self) -> None:
        result = self.classifier.classify("My glucose is 112. Is this normal?")

        self.assertEqual(result.risk_level, ClassifiedRiskLevel.MEDIUM)
        self.assertEqual(result.flags, ["interpretation_request"])
        self.assertIn("Interpretation", result.reason)

    def test_high_for_diagnosis_intent(self) -> None:
        result = self.classifier.classify("Can you diagnose why I have these symptoms?")

        self.assertEqual(result.risk_level, ClassifiedRiskLevel.HIGH)
        self.assertEqual(result.flags, ["diagnosis_intent"])

    def test_high_for_medication_suggestion(self) -> None:
        result = self.classifier.classify("What medication should I take for this rash?")

        self.assertEqual(result.risk_level, ClassifiedRiskLevel.HIGH)
        self.assertEqual(result.flags, ["medication_suggestion"])

    def test_critical_for_emergency_intent(self) -> None:
        result = self.classifier.classify("This is an emergency. I have chest pain and cannot breathe.")

        self.assertEqual(result.risk_level, ClassifiedRiskLevel.CRITICAL)
        self.assertIn("emergency_intent", result.flags)
        self.assertIn("life-threatening", result.reason)

    def test_mixed_intent_uses_highest_risk(self) -> None:
        result = self.classifier.classify(
            "Please explain my lab result and diagnose my chest pain."
        )

        self.assertEqual(result.risk_level, ClassifiedRiskLevel.CRITICAL)
        self.assertEqual(result.flags, ["emergency_intent"])

    def test_mixed_high_intent_includes_high_flags_only(self) -> None:
        result = self.classifier.classify(
            "Is this normal, and what medication should I take?"
        )

        self.assertEqual(result.risk_level, ClassifiedRiskLevel.HIGH)
        self.assertEqual(result.flags, ["medication_suggestion"])

    def test_default_low_without_trigger_flags(self) -> None:
        result = self.classifier.classify("Please summarize the provided educational note.")

        self.assertEqual(result.risk_level, ClassifiedRiskLevel.LOW)
        self.assertEqual(result.flags, [])

    def test_deterministic_behavior(self) -> None:
        text = "Does this mean I have diabetes?"

        first = self.classifier.classify(text)
        second = self.classifier.classify(text)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
