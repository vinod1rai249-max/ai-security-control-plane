"""Deterministic policy engine for post-classification decisions."""

from dataclasses import dataclass
from enum import StrEnum

from src.models.requests import Domain, Role
from src.services.risk_classifier import ClassifiedRiskLevel


class PolicyDecision(StrEnum):
    """Decisions returned by the deterministic policy engine."""

    ALLOW = "allow"
    BLOCK = "block"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    ALLOW_WITH_DISCLAIMER = "allow_with_disclaimer"


@dataclass(frozen=True)
class PolicyResult:
    """Explainable policy decision for a classified request."""

    decision: PolicyDecision
    reason: str
    required_disclaimer: str | None
    policy_flags: list[str]


class PolicyEngine:
    """Applies deterministic policy rules after risk classification."""

    _STANDARD_DISCLAIMER = (
        "This is not a substitute for professional medical advice. "
        "Please consult a qualified clinician for clinical decisions."
    )

    def evaluate(
        self,
        sanitized_query: str,
        risk_level: ClassifiedRiskLevel | str,
        flags: list[str],
        domain: Domain | str,
        role: Role | str = Role.PATIENT,
    ) -> PolicyResult:
        """Return an explainable policy decision without LLM or external calls.

        Security contract: this method assumes PHI has already been scrubbed
        and risk classification has already run. It uses only deterministic
        local rules, blocks unsafe or unsupported requests fail-closed, and
        does not route to a model or call external services.
        """

        if not sanitized_query.strip():
            return PolicyResult(
                decision=PolicyDecision.BLOCK,
                reason="Empty sanitized query cannot be processed safely.",
                required_disclaimer=None,
                policy_flags=["empty_query"],
            )

        parsed_domain = self._parse_domain(domain)
        if parsed_domain is None:
            return PolicyResult(
                decision=PolicyDecision.BLOCK,
                reason="Domain is not supported by the approved policy contract.",
                required_disclaimer=None,
                policy_flags=["unknown_domain"],
            )

        parsed_risk = self._parse_risk_level(risk_level)
        if parsed_risk is None:
            return PolicyResult(
                decision=PolicyDecision.BLOCK,
                reason="Risk level is not recognized by the policy engine.",
                required_disclaimer=None,
                policy_flags=["unknown_risk_level"],
            )

        normalized_flags = set(flags)
        parsed_role = self._parse_role(role) or Role.PATIENT

        if parsed_role == Role.LAB_TECH and parsed_domain != Domain.LAB_INTERPRETATION:
            return PolicyResult(
                decision=PolicyDecision.BLOCK,
                reason="Lab tech role is limited to reference ranges and lab interpretation.",
                required_disclaimer=None,
                policy_flags=["role_domain_not_allowed"],
            )

        if parsed_role in {Role.PATIENT, Role.LAB_TECH, Role.ADMIN} and normalized_flags.intersection(
            {"diagnosis_intent", "medication_suggestion"}
        ):
            return PolicyResult(
                decision=PolicyDecision.BLOCK,
                reason=f"{parsed_role.value} role cannot receive diagnosis or medication advice.",
                required_disclaimer=None,
                policy_flags=self._selected_flags(
                    normalized_flags,
                    ["diagnosis_intent", "medication_suggestion"],
                ),
            )

        if parsed_risk == ClassifiedRiskLevel.CRITICAL:
            critical_decision = (
                PolicyDecision.NEEDS_HUMAN_REVIEW
                if normalized_flags.intersection(
                    {
                        "critical_potassium",
                        "critical_inr",
                        "critical_glucose",
                        "critical_egfr",
                        "critical_creatinine",
                    }
                )
                else PolicyDecision.BLOCK
            )
            return PolicyResult(
                decision=critical_decision,
                reason="Emergency intent must be escalated to emergency services or a qualified provider.",
                required_disclaimer=None,
                policy_flags=self._selected_flags(
                    normalized_flags,
                    [
                        "emergency_intent",
                        "critical_potassium",
                        "critical_inr",
                        "critical_glucose",
                        "critical_egfr",
                        "critical_creatinine",
                    ],
                ),
            )

        if parsed_risk == ClassifiedRiskLevel.HIGH:
            unsafe_flags = self._selected_flags(
                normalized_flags,
                ["diagnosis_intent", "medication_suggestion"],
            )
            if unsafe_flags:
                if parsed_role == Role.PHYSICIAN and "diagnosis_intent" in unsafe_flags:
                    return PolicyResult(
                        decision=PolicyDecision.ALLOW_WITH_DISCLAIMER,
                        reason="Physician diagnosis-adjacent explanation may proceed with a disclaimer.",
                        required_disclaimer=self._STANDARD_DISCLAIMER,
                        policy_flags=unsafe_flags + ["physician_disclaimer_required"],
                    )
                return PolicyResult(
                    decision=PolicyDecision.BLOCK,
                    reason="Diagnosis or medication requests require clinician oversight and are blocked.",
                    required_disclaimer=None,
                    policy_flags=unsafe_flags,
                )

            return PolicyResult(
                decision=PolicyDecision.NEEDS_HUMAN_REVIEW,
                reason="High-risk request requires human review before processing.",
                required_disclaimer=None,
                policy_flags=["high_risk_review_required"],
            )

        if parsed_risk == ClassifiedRiskLevel.MEDIUM and "interpretation_request" in normalized_flags:
            return PolicyResult(
                decision=PolicyDecision.ALLOW_WITH_DISCLAIMER,
                reason="Medium-risk interpretation may proceed with a medical disclaimer.",
                required_disclaimer=self._STANDARD_DISCLAIMER,
                policy_flags=["disclaimer_required"],
            )

        if (
            parsed_risk == ClassifiedRiskLevel.LOW
            and parsed_domain == Domain.LAB_INTERPRETATION
            and "lab_explanation" in normalized_flags
        ):
            return PolicyResult(
                decision=PolicyDecision.ALLOW,
                reason="Low-risk lab explanation is allowed.",
                required_disclaimer=None,
                policy_flags=["low_risk_lab_allowed"],
            )

        if parsed_risk == ClassifiedRiskLevel.LOW:
            return PolicyResult(
                decision=PolicyDecision.ALLOW,
                reason="Low-risk request is allowed.",
                required_disclaimer=None,
                policy_flags=["low_risk_allowed"],
            )

        return PolicyResult(
            decision=PolicyDecision.BLOCK,
            reason="Request did not match an allowed policy path.",
            required_disclaimer=None,
            policy_flags=["no_allowed_policy_path"],
        )

    @staticmethod
    def _parse_domain(domain: Domain | str) -> Domain | None:
        if isinstance(domain, Domain):
            return domain

        try:
            return Domain(domain)
        except ValueError:
            return None

    @staticmethod
    def _parse_risk_level(risk_level: ClassifiedRiskLevel | str) -> ClassifiedRiskLevel | None:
        if isinstance(risk_level, ClassifiedRiskLevel):
            return risk_level

        try:
            return ClassifiedRiskLevel(risk_level)
        except ValueError:
            return None

    @staticmethod
    def _parse_role(role: Role | str) -> Role | None:
        if isinstance(role, Role):
            return role

        try:
            return Role(role)
        except ValueError:
            return None

    @staticmethod
    def _selected_flags(found_flags: set[str], ordered_flags: list[str]) -> list[str]:
        return [flag for flag in ordered_flags if flag in found_flags]


def evaluate_policy(
    sanitized_query: str,
    risk_level: ClassifiedRiskLevel | str,
    flags: list[str],
    domain: Domain | str,
    role: Role | str = Role.PATIENT,
) -> PolicyResult:
    """Evaluate request policy using the default deterministic engine."""

    return PolicyEngine().evaluate(
        sanitized_query=sanitized_query,
        risk_level=risk_level,
        flags=flags,
        domain=domain,
        role=role,
    )
