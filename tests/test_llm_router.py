import unittest

from src.services.llm_router import LLMRouter
from src.services.policy_engine import PolicyDecision
from src.services.risk_classifier import ClassifiedRiskLevel


class TestLLMRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.router = LLMRouter()

    def test_blocked_policy_uses_no_llm(self) -> None:
        result = self.router.route(
            risk_level=ClassifiedRiskLevel.LOW,
            decision=PolicyDecision.BLOCK,
            requires_human_review=False,
        )

        self.assertFalse(result.use_llm)
        self.assertEqual(result.selected_model, "none")
        self.assertIn("block", result.reason)

    def test_critical_risk_uses_no_llm(self) -> None:
        result = self.router.route(
            risk_level=ClassifiedRiskLevel.CRITICAL,
            decision=PolicyDecision.ALLOW,
            requires_human_review=False,
        )

        self.assertFalse(result.use_llm)
        self.assertEqual(result.selected_model, "none")
        self.assertIn("Critical", result.reason)

    def test_human_review_uses_no_llm(self) -> None:
        result = self.router.route(
            risk_level=ClassifiedRiskLevel.MEDIUM,
            decision=PolicyDecision.NEEDS_HUMAN_REVIEW,
            requires_human_review=True,
        )

        self.assertFalse(result.use_llm)
        self.assertEqual(result.selected_model, "none")
        self.assertIn("human review", result.reason)

    def test_low_risk_allows_llm(self) -> None:
        result = self.router.route(
            risk_level=ClassifiedRiskLevel.LOW,
            decision=PolicyDecision.ALLOW,
            requires_human_review=False,
        )

        self.assertTrue(result.use_llm)
        self.assertEqual(result.selected_model, "mock")

    def test_medium_risk_allows_llm(self) -> None:
        result = self.router.route(
            risk_level=ClassifiedRiskLevel.MEDIUM,
            decision=PolicyDecision.ALLOW_WITH_DISCLAIMER,
            requires_human_review=False,
        )

        self.assertTrue(result.use_llm)
        self.assertEqual(result.selected_model, "mock")

    def test_human_review_flag_overrides_allow_decision(self) -> None:
        result = self.router.route(
            risk_level=ClassifiedRiskLevel.LOW,
            decision=PolicyDecision.ALLOW,
            requires_human_review=True,
        )

        self.assertFalse(result.use_llm)
        self.assertEqual(result.selected_model, "none")

    def test_deterministic_result(self) -> None:
        kwargs = {
            "risk_level": "medium",
            "decision": "allow_with_disclaimer",
            "requires_human_review": False,
        }

        first = self.router.route(**kwargs)
        second = self.router.route(**kwargs)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
