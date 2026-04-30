"""Optional mock LLM guardrail judge for ambiguous safety cases."""

from dataclasses import dataclass
from typing import Any

from src.services.policy_engine import PolicyDecision
from src.services.risk_classifier import ClassifiedRiskLevel


@dataclass(frozen=True)
class GuardrailJudgeResult:
    """Decision returned by the optional guardrail judge."""

    decision: PolicyDecision
    reason: str
    judge_ran: bool
    used_rule_based_fallback: bool
    judge_flags: list[str]


class LLMGuardrailJudge:
    """Mock guardrail judge that can only make rule decisions stricter.

    Security contract: this class does not call a real LLM. It only evaluates
    a caller-supplied mock judge output for medium or ambiguous cases, cannot
    override hard blocks, and falls back to the existing rule-based decision if
    the mock output is invalid or less strict.
    """

    _STRICTNESS = {
        PolicyDecision.ALLOW: 1,
        PolicyDecision.ALLOW_WITH_DISCLAIMER: 2,
        PolicyDecision.NEEDS_HUMAN_REVIEW: 3,
        PolicyDecision.BLOCK: 4,
    }

    def judge(
        self,
        rule_based_decision: PolicyDecision | str,
        risk_level: ClassifiedRiskLevel | str,
        flags: list[str],
        mock_judge_output: dict[str, Any] | None = None,
    ) -> GuardrailJudgeResult:
        """Return the rule decision or a stricter mock judge decision."""

        parsed_decision = self._parse_policy_decision(rule_based_decision)
        parsed_risk = self._parse_risk_level(risk_level)
        if parsed_decision is None:
            return GuardrailJudgeResult(
                decision=PolicyDecision.BLOCK,
                reason="Rule-based decision was invalid; blocked fail-closed.",
                judge_ran=False,
                used_rule_based_fallback=True,
                judge_flags=["invalid_rule_decision"],
            )

        if parsed_decision == PolicyDecision.BLOCK:
            return GuardrailJudgeResult(
                decision=parsed_decision,
                reason="Hard block cannot be overridden by guardrail judge.",
                judge_ran=False,
                used_rule_based_fallback=True,
                judge_flags=["hard_block_preserved"],
            )

        if not self._should_run(parsed_risk, flags):
            return GuardrailJudgeResult(
                decision=parsed_decision,
                reason="Guardrail judge only runs for medium or ambiguous cases.",
                judge_ran=False,
                used_rule_based_fallback=True,
                judge_flags=["judge_not_applicable"],
            )

        judge_decision = self._parse_judge_output(mock_judge_output)
        if judge_decision is None:
            return GuardrailJudgeResult(
                decision=parsed_decision,
                reason="Invalid guardrail judge output; using rule-based decision.",
                judge_ran=True,
                used_rule_based_fallback=True,
                judge_flags=["invalid_judge_output"],
            )

        if self._STRICTNESS[judge_decision] < self._STRICTNESS[parsed_decision]:
            return GuardrailJudgeResult(
                decision=parsed_decision,
                reason="Guardrail judge cannot make the rule-based decision less strict.",
                judge_ran=True,
                used_rule_based_fallback=True,
                judge_flags=["less_strict_judge_output_rejected"],
            )

        return GuardrailJudgeResult(
            decision=judge_decision,
            reason="Guardrail judge decision accepted because it preserves or increases strictness.",
            judge_ran=True,
            used_rule_based_fallback=False,
            judge_flags=["judge_output_accepted"],
        )

    @staticmethod
    def _should_run(risk_level: ClassifiedRiskLevel | None, flags: list[str]) -> bool:
        return risk_level == ClassifiedRiskLevel.MEDIUM or "ambiguous" in set(flags)

    @staticmethod
    def _parse_policy_decision(decision: PolicyDecision | str) -> PolicyDecision | None:
        if isinstance(decision, PolicyDecision):
            return decision

        try:
            return PolicyDecision(str(decision))
        except ValueError:
            return None

    @staticmethod
    def _parse_risk_level(risk_level: ClassifiedRiskLevel | str) -> ClassifiedRiskLevel | None:
        if isinstance(risk_level, ClassifiedRiskLevel):
            return risk_level

        try:
            return ClassifiedRiskLevel(str(risk_level))
        except ValueError:
            return None

    @staticmethod
    def _parse_judge_output(output: dict[str, Any] | None) -> PolicyDecision | None:
        if not isinstance(output, dict):
            return None

        decision = output.get("decision")
        if not isinstance(decision, str):
            return None

        try:
            return PolicyDecision(decision)
        except ValueError:
            return None


def judge_guardrail(
    rule_based_decision: PolicyDecision | str,
    risk_level: ClassifiedRiskLevel | str,
    flags: list[str],
    mock_judge_output: dict[str, Any] | None = None,
) -> GuardrailJudgeResult:
    """Run the default mock guardrail judge."""

    return LLMGuardrailJudge().judge(
        rule_based_decision=rule_based_decision,
        risk_level=risk_level,
        flags=flags,
        mock_judge_output=mock_judge_output,
    )
