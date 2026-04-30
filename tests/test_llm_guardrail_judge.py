import unittest

from src.services.llm_guardrail_judge import LLMGuardrailJudge, judge_guardrail
from src.services.policy_engine import PolicyDecision
from src.services.risk_classifier import ClassifiedRiskLevel


class TestLLMGuardrailJudge(unittest.TestCase):
    def setUp(self) -> None:
        self.judge = LLMGuardrailJudge()

    def test_medium_case_can_be_made_stricter(self) -> None:
        result = self.judge.judge(
            rule_based_decision=PolicyDecision.ALLOW_WITH_DISCLAIMER,
            risk_level=ClassifiedRiskLevel.MEDIUM,
            flags=["interpretation_request"],
            mock_judge_output={"decision": "needs_human_review"},
        )

        self.assertTrue(result.judge_ran)
        self.assertFalse(result.used_rule_based_fallback)
        self.assertEqual(result.decision, PolicyDecision.NEEDS_HUMAN_REVIEW)
        self.assertIn("judge_output_accepted", result.judge_flags)

    def test_low_non_ambiguous_case_does_not_run(self) -> None:
        result = self.judge.judge(
            rule_based_decision=PolicyDecision.ALLOW,
            risk_level=ClassifiedRiskLevel.LOW,
            flags=["lab_explanation"],
            mock_judge_output={"decision": "block"},
        )

        self.assertFalse(result.judge_ran)
        self.assertTrue(result.used_rule_based_fallback)
        self.assertEqual(result.decision, PolicyDecision.ALLOW)

    def test_ambiguous_case_runs_even_when_low_risk(self) -> None:
        result = self.judge.judge(
            rule_based_decision=PolicyDecision.ALLOW,
            risk_level=ClassifiedRiskLevel.LOW,
            flags=["ambiguous"],
            mock_judge_output={"decision": "allow_with_disclaimer"},
        )

        self.assertTrue(result.judge_ran)
        self.assertEqual(result.decision, PolicyDecision.ALLOW_WITH_DISCLAIMER)

    def test_hard_block_cannot_be_overridden(self) -> None:
        result = self.judge.judge(
            rule_based_decision=PolicyDecision.BLOCK,
            risk_level=ClassifiedRiskLevel.MEDIUM,
            flags=["interpretation_request"],
            mock_judge_output={"decision": "allow"},
        )

        self.assertFalse(result.judge_ran)
        self.assertTrue(result.used_rule_based_fallback)
        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertIn("hard_block_preserved", result.judge_flags)

    def test_less_strict_judge_output_falls_back_to_rule_decision(self) -> None:
        result = self.judge.judge(
            rule_based_decision=PolicyDecision.NEEDS_HUMAN_REVIEW,
            risk_level=ClassifiedRiskLevel.MEDIUM,
            flags=["interpretation_request"],
            mock_judge_output={"decision": "allow_with_disclaimer"},
        )

        self.assertTrue(result.judge_ran)
        self.assertTrue(result.used_rule_based_fallback)
        self.assertEqual(result.decision, PolicyDecision.NEEDS_HUMAN_REVIEW)
        self.assertIn("less_strict_judge_output_rejected", result.judge_flags)

    def test_invalid_judge_output_falls_back_to_rule_decision(self) -> None:
        result = self.judge.judge(
            rule_based_decision=PolicyDecision.ALLOW_WITH_DISCLAIMER,
            risk_level=ClassifiedRiskLevel.MEDIUM,
            flags=["interpretation_request"],
            mock_judge_output={"decision": "approve_everything"},
        )

        self.assertTrue(result.judge_ran)
        self.assertTrue(result.used_rule_based_fallback)
        self.assertEqual(result.decision, PolicyDecision.ALLOW_WITH_DISCLAIMER)
        self.assertIn("invalid_judge_output", result.judge_flags)

    def test_invalid_rule_based_decision_blocks_fail_closed(self) -> None:
        result = self.judge.judge(
            rule_based_decision="not_a_decision",
            risk_level=ClassifiedRiskLevel.MEDIUM,
            flags=["interpretation_request"],
            mock_judge_output={"decision": "allow"},
        )

        self.assertFalse(result.judge_ran)
        self.assertTrue(result.used_rule_based_fallback)
        self.assertEqual(result.decision, PolicyDecision.BLOCK)

    def test_convenience_function_uses_default_judge(self) -> None:
        result = judge_guardrail(
            rule_based_decision="allow_with_disclaimer",
            risk_level="medium",
            flags=["interpretation_request"],
            mock_judge_output={"decision": "block"},
        )

        self.assertEqual(result.decision, PolicyDecision.BLOCK)


if __name__ == "__main__":
    unittest.main()
