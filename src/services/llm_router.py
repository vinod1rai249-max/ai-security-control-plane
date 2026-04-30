"""Pure LLM routing decision layer."""

from dataclasses import dataclass

from src.models.responses import RiskLevel
from src.services.policy_engine import PolicyDecision
from src.services.risk_classifier import ClassifiedRiskLevel


@dataclass(frozen=True)
class LLMRouteDecision:
    """Decision describing whether a request may use an LLM."""

    use_llm: bool
    reason: str
    selected_model: str


class LLMRouter:
    """Determines whether the pipeline may call an LLM.

    This task intentionally implements only the deterministic routing gate.
    It does not call providers, build prompts, handle retries, or select real
    vendor models.
    """

    def route(
        self,
        risk_level: ClassifiedRiskLevel | RiskLevel | str,
        decision: PolicyDecision | str,
        requires_human_review: bool,
    ) -> LLMRouteDecision:
        """Return whether an LLM is allowed for this classified request.

        Security contract: this method assumes risk classification and policy
        evaluation have already completed. It blocks model use for blocked,
        human-review, and critical paths, and never calls an external model.
        """

        parsed_risk = self._parse_risk_level(risk_level)
        parsed_decision = self._parse_policy_decision(decision)

        if parsed_decision is None:
            return LLMRouteDecision(
                use_llm=False,
                reason="Policy decision is not recognized; LLM use is blocked fail-closed.",
                selected_model="none",
            )

        if parsed_risk is None:
            return LLMRouteDecision(
                use_llm=False,
                reason="Risk level is not recognized; LLM use is blocked fail-closed.",
                selected_model="none",
            )

        if parsed_decision == PolicyDecision.BLOCK:
            return LLMRouteDecision(
                use_llm=False,
                reason="Policy decision is block; LLM must not be used.",
                selected_model="none",
            )

        if parsed_decision == PolicyDecision.NEEDS_HUMAN_REVIEW or requires_human_review:
            return LLMRouteDecision(
                use_llm=False,
                reason="Request requires human review; LLM must not be used.",
                selected_model="none",
            )

        if parsed_risk == ClassifiedRiskLevel.CRITICAL:
            return LLMRouteDecision(
                use_llm=False,
                reason="Critical risk requests are blocked from LLM routing.",
                selected_model="none",
            )

        if parsed_risk in {ClassifiedRiskLevel.LOW, ClassifiedRiskLevel.MEDIUM} and parsed_decision in {
            PolicyDecision.ALLOW,
            PolicyDecision.ALLOW_WITH_DISCLAIMER,
        }:
            return LLMRouteDecision(
                use_llm=True,
                reason="Risk and policy decision allow LLM use.",
                selected_model="mock",
            )

        return LLMRouteDecision(
            use_llm=False,
            reason="No approved routing path matched; LLM use is blocked fail-closed.",
            selected_model="none",
        )

    @staticmethod
    def _parse_risk_level(risk_level: ClassifiedRiskLevel | RiskLevel | str) -> ClassifiedRiskLevel | None:
        if isinstance(risk_level, ClassifiedRiskLevel):
            return risk_level

        value = risk_level.value if isinstance(risk_level, RiskLevel) else risk_level
        try:
            return ClassifiedRiskLevel(str(value).lower())
        except ValueError:
            return None

    @staticmethod
    def _parse_policy_decision(decision: PolicyDecision | str) -> PolicyDecision | None:
        if isinstance(decision, PolicyDecision):
            return decision

        try:
            return PolicyDecision(str(decision).lower())
        except ValueError:
            return None


def route_llm(
    risk_level: ClassifiedRiskLevel | RiskLevel | str,
    decision: PolicyDecision | str,
    requires_human_review: bool,
) -> LLMRouteDecision:
    """Route LLM use through the default deterministic router."""

    return LLMRouter().route(
        risk_level=risk_level,
        decision=decision,
        requires_human_review=requires_human_review,
    )
