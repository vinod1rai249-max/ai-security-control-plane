import unittest
from unittest.mock import patch
from uuid import uuid4

from src.api.routes.analyze import analyze_request, precheck_request
from src.models.requests import Domain, Role, SecurityRequest
from src.services.audit_logger import AuditLogger, InMemoryAuditSink


class FailingLLMClient:
    model = "openai/gpt-4o-mini"

    def __init__(self) -> None:
        self.called = False

    def generate_response(self, query: str) -> dict[str, str]:
        self.called = True
        raise TimeoutError("openrouter timeout")


class SafeLLMClient:
    model = "configured-model"

    def __init__(self) -> None:
        self.called = False

    def generate_response(self, query: str) -> dict[str, str]:
        self.called = True
        return {
            "summary": "General educational lab explanation.",
            "safety_assessment": "No unsafe output was generated.",
            "recommendation": "Review general educational material.",
            "disclaimer": "For personalized medical advice, please consult a healthcare provider.",
        }


class TestUpgradeBehavior(unittest.TestCase):
    def _request(
        self,
        query: str,
        role: Role = Role.PATIENT,
        domain: Domain = Domain.LAB_INTERPRETATION,
    ) -> SecurityRequest:
        return SecurityRequest(
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            query=query,
            domain=domain,
            role=role,
            metadata={"source": "upgrade_test"},
        )

    def test_lazy_llm_loading_blocked_diagnosis_without_api_key(self) -> None:
        with patch("src.api.routes.analyze.get_llm_client", side_effect=RuntimeError("missing key")):
            status_code, response = analyze_request(
                self._request("Can you diagnose this symptom pattern?", Role.PATIENT, Domain.CLINICAL_SUMMARY)
            )

        self.assertEqual(status_code, 403)
        self.assertEqual(response.decision, "block")
        self.assertEqual(response.selected_model, "none")

    def test_precheck_allowed_request(self) -> None:
        status_code, response = precheck_request(
            self._request("Please explain this LDL reference range.", Role.LAB_TECH)
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.decision, "allow")
        self.assertEqual(response.risk_level, "low")

    def test_precheck_blocked_diagnosis(self) -> None:
        status_code, response = precheck_request(
            self._request("Do I have diabetes?", Role.PATIENT, Domain.CLINICAL_SUMMARY)
        )

        self.assertEqual(status_code, 403)
        self.assertEqual(response.decision, "block")
        self.assertIn("diagnosis", response.blocked_reason.lower())

    def test_postcheck_phi_leakage_blocked_by_analyze_validator(self) -> None:
        llm_client = SafeLLMClient()
        llm_client.generate_response = lambda query: {
            "summary": "Patient Jane Doe has a general lab result.",
            "safety_assessment": "No unsafe output was generated.",
            "recommendation": "Review general educational material.",
            "disclaimer": "For personalized medical advice, please consult a healthcare provider.",
        }

        status_code, response = analyze_request(
            self._request("Please explain this lab result reference range.", Role.PATIENT),
            llm_client=llm_client,
        )

        self.assertEqual(status_code, 503)
        self.assertEqual(response.validation_status, "invalid")
        self.assertIn("phi_name_detected", response.violations)

    def test_audit_does_not_store_raw_query(self) -> None:
        sink = InMemoryAuditSink()
        logger = AuditLogger(sink=sink)
        query = "Patient Jane Doe asks about LDL reference range."

        status_code, response = analyze_request(
            self._request(query, Role.PATIENT),
            llm_client=FailingLLMClient(),
            audit_logger=logger,
        )

        self.assertEqual(status_code, 200)
        stored_event = sink.get(response.audit_id)
        serialized_event = str(stored_event.model_dump())
        self.assertEqual(len(stored_event.query_hash), 64)
        self.assertNotIn("Jane Doe", serialized_event)
        self.assertNotIn(query, serialized_event)

    def test_rbac_patient_vs_physician_behavior(self) -> None:
        patient_status, patient_response = analyze_request(
            self._request("Does this mean I have diabetes?", Role.PATIENT, Domain.CLINICAL_SUMMARY)
        )
        physician_status, physician_response = analyze_request(
            self._request("Can you diagnose whether this could be diabetes?", Role.PHYSICIAN, Domain.CLINICAL_SUMMARY),
            llm_client=FailingLLMClient(),
        )

        self.assertEqual(patient_status, 403)
        self.assertEqual(patient_response.decision, "block")
        self.assertEqual(physician_status, 200)
        self.assertEqual(physician_response.decision, "allow_with_disclaimer")

    def test_llm_circuit_breaker_fallback(self) -> None:
        llm_client = FailingLLMClient()
        status_code, response = analyze_request(
            self._request("Please explain this lab result reference range.", Role.PATIENT),
            llm_client=llm_client,
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(llm_client.called)
        self.assertFalse(response.use_llm)
        self.assertEqual(response.selected_model, "fallback")
        self.assertEqual(response.answer["summary"], "This appears to be a general health-related question.")

    def test_safe_query_uses_configured_model_when_env_exists(self) -> None:
        llm_client = SafeLLMClient()
        status_code, response = analyze_request(
            self._request("Please explain this lab result reference range.", Role.PATIENT),
            llm_client=llm_client,
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(llm_client.called)
        self.assertEqual(response.selected_model, "configured-model")

    def test_clinical_critical_value_routes_to_review(self) -> None:
        status_code, response = precheck_request(
            self._request("Potassium is 7.1 on this lab result.", Role.PHYSICIAN)
        )

        self.assertEqual(status_code, 403)
        self.assertEqual(response.decision, "needs_human_review")
        self.assertEqual(response.risk_level, "critical")


if __name__ == "__main__":
    unittest.main()
