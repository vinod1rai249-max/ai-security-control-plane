import unittest

from src.services.output_validator import OutputValidationStatus, OutputValidator
from src.services.risk_classifier import ClassifiedRiskLevel


class TestOutputValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = OutputValidator()

    def test_valid_safe_response_passes(self) -> None:
        result = self.validator.validate(
            response_text="This lab value is within the listed reference range.",
            confidence_score=0.82,
            risk_level=ClassifiedRiskLevel.LOW,
        )

        self.assertEqual(result.validation_status, OutputValidationStatus.VALID)
        self.assertEqual(result.violations, [])
        self.assertIsNotNone(result.corrected_response)

    def test_response_with_phi_fails(self) -> None:
        result = self.validator.validate(
            response_text="Patient Jane Doe can be reached at jane.doe@example.org.",
            confidence_score=0.7,
            risk_level=ClassifiedRiskLevel.LOW,
        )

        self.assertEqual(result.validation_status, OutputValidationStatus.INVALID)
        self.assertIn("phi_name_detected", result.violations)
        self.assertIn("phi_email_detected", result.violations)
        self.assertIsNone(result.corrected_response)

    def test_diagnosis_statement_fails(self) -> None:
        result = self.validator.validate(
            response_text="Based on this result, you have diabetes.",
            confidence_score=0.7,
            risk_level=ClassifiedRiskLevel.HIGH,
        )

        self.assertEqual(result.validation_status, OutputValidationStatus.INVALID)
        self.assertIn("diagnosis_claim_detected", result.violations)

    def test_medication_advice_fails(self) -> None:
        result = self.validator.validate(
            response_text="You should take 500 mg metformin daily.",
            confidence_score=0.7,
            risk_level=ClassifiedRiskLevel.HIGH,
        )

        self.assertEqual(result.validation_status, OutputValidationStatus.INVALID)
        self.assertIn("medication_advice_detected", result.violations)

    def test_missing_disclaimer_fails_for_medium_risk(self) -> None:
        result = self.validator.validate(
            response_text="This value may be slightly elevated.",
            confidence_score=0.7,
            risk_level=ClassifiedRiskLevel.MEDIUM,
        )

        self.assertEqual(result.validation_status, OutputValidationStatus.INVALID)
        self.assertIn("missing_required_disclaimer", result.violations)

    def test_missing_disclaimer_fails_for_high_risk(self) -> None:
        result = self.validator.validate(
            response_text="This result needs clinical interpretation.",
            confidence_score=0.7,
            risk_level=ClassifiedRiskLevel.HIGH,
        )

        self.assertEqual(result.validation_status, OutputValidationStatus.INVALID)
        self.assertIn("missing_required_disclaimer", result.violations)

    def test_disclaimer_passes_for_medium_risk(self) -> None:
        result = self.validator.validate(
            response_text="This value may be elevated. Please consult a healthcare provider.",
            confidence_score=0.7,
            risk_level="medium",
        )

        self.assertEqual(result.validation_status, OutputValidationStatus.VALID)
        self.assertEqual(result.violations, [])

    def test_confidence_out_of_range_fails(self) -> None:
        result = self.validator.validate(
            response_text="This appears educational only.",
            confidence_score=1.2,
            risk_level=ClassifiedRiskLevel.LOW,
        )

        self.assertEqual(result.validation_status, OutputValidationStatus.INVALID)
        self.assertIn("confidence_score_out_of_range", result.violations)

    def test_deterministic_repeated_result(self) -> None:
        kwargs = {
            "response_text": "This value may be elevated. Please consult a healthcare provider.",
            "confidence_score": 0.7,
            "risk_level": "MEDIUM",
        }

        first = self.validator.validate(**kwargs)
        second = self.validator.validate(**kwargs)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
