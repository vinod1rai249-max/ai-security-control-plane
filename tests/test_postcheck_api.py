import unittest
from uuid import uuid4

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None

from main import create_app
from src.models.requests import Domain
from src.services.risk_classifier import ClassifiedRiskLevel


@unittest.skipIf(TestClient is None, "FastAPI TestClient is not installed")
class TestPostcheckApi(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        if app is None:
            self.skipTest("FastAPI is not installed")
        self.client = TestClient(app)

    def _payload(
        self,
        llm_response: str,
        risk_level: ClassifiedRiskLevel = ClassifiedRiskLevel.LOW,
        confidence_score: float = 1.0,
    ) -> dict[str, str | float]:
        return {
            "request_id": str(uuid4()),
            "session_id": str(uuid4()),
            "user_id": str(uuid4()),
            "llm_response": llm_response,
            "risk_level": risk_level.value,
            "domain": Domain.LAB_INTERPRETATION.value,
            "confidence_score": confidence_score,
        }

    def test_valid_response_is_valid(self) -> None:
        safe_text = "This is a general educational explanation."
        response = self.client.post("/postcheck", json=self._payload(safe_text))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["validation_status"], "valid")
        self.assertEqual(data["violations"], [])
        self.assertEqual(data["safe_response"], safe_text)
        self.assertTrue(data["audit_id"])

    def test_diagnosis_response_is_invalid(self) -> None:
        response = self.client.post(
            "/postcheck",
            json=self._payload("You have diabetes."),
        )

        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertEqual(data["validation_status"], "invalid")
        self.assertIn("diagnosis_claim_detected", data["violations"])
        self.assertEqual(data["safe_response"], "")

    def test_missing_disclaimer_is_invalid_for_medium_risk(self) -> None:
        response = self.client.post(
            "/postcheck",
            json=self._payload(
                "This is a general interpretation of the result.",
                ClassifiedRiskLevel.MEDIUM,
            ),
        )

        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertEqual(data["validation_status"], "invalid")
        self.assertIn("missing_required_disclaimer", data["violations"])
        self.assertEqual(data["safe_response"], "")

    def test_invalid_confidence_is_invalid(self) -> None:
        response = self.client.post(
            "/postcheck",
            json=self._payload(
                "This is a general educational explanation.",
                ClassifiedRiskLevel.LOW,
                confidence_score=1.5,
            ),
        )

        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertEqual(data["validation_status"], "invalid")
        self.assertIn("confidence_score_out_of_range", data["violations"])
        self.assertEqual(data["safe_response"], "")


if __name__ == "__main__":
    unittest.main()
