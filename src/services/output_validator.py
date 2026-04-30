"""Deterministic output validator for AI responses."""

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Pattern

from src.models.responses import RiskLevel
from src.services.risk_classifier import ClassifiedRiskLevel


class OutputValidationStatus(StrEnum):
    """Validation states returned before a response reaches the user."""

    VALID = "valid"
    INVALID = "invalid"
    REQUIRES_REVIEW = "requires_review"


@dataclass(frozen=True)
class OutputValidationResult:
    """Explainable result from output validation."""

    validation_status: OutputValidationStatus
    violations: list[str]
    corrected_response: str | None = None


@dataclass(frozen=True)
class _ValidationPattern:
    violation: str
    pattern: Pattern[str]


class OutputValidator:
    """Validates final AI output using deterministic safety checks."""

    _DISCLAIMER_PATTERN = re.compile(
        r"\bconsult\s+(a\s+)?(qualified\s+)?(healthcare\s+provider|clinician|doctor|physician)\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self._phi_patterns = [
            _ValidationPattern(
                "phi_email_detected",
                re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
            ),
            _ValidationPattern(
                "phi_phone_detected",
                re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"),
            ),
            _ValidationPattern(
                "phi_mrn_detected",
                re.compile(
                    r"\b(?:MRN|Medical Record(?: Number)?|Medical Record No\.?)"
                    r"\s*[:#-]?\s*[A-Z]{0,3}\d{6,10}\b",
                    re.IGNORECASE,
                ),
            ),
            _ValidationPattern(
                "phi_insurance_id_detected",
                re.compile(
                    r"\b(?:Insurance(?: ID| Number)?|Policy(?: ID| Number)?)"
                    r"\s*[:#-]?\s*[A-Z0-9-]{8,16}\b",
                    re.IGNORECASE,
                ),
            ),
            _ValidationPattern(
                "phi_name_detected",
                re.compile(
                    r"\b(?:Patient|Name|Member)\s*(?:Name)?\s*[:#-]?\s*"
                    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b"
                ),
            ),
        ]
        self._diagnosis_patterns = [
            _ValidationPattern(
                "diagnosis_claim_detected",
                re.compile(
                    r"\b(you\s+have\s+[A-Za-z][A-Za-z\s-]*|you\s+are\s+diagnosed\s+with)\b",
                    re.IGNORECASE,
                ),
            ),
        ]
        self._medication_patterns = [
            _ValidationPattern(
                "medication_advice_detected",
                re.compile(
                    r"\b("
                    r"take\s+\d+(\.\d+)?\s*(mg|mcg|g|ml|units?)|"
                    r"\d+(\.\d+)?\s*(mg|mcg|g|ml|units?)\s+(daily|twice\s+daily|per\s+day|every\s+\d+\s+hours)|"
                    r"you\s+should\s+take|ask\s+for\s+a\s+prescription|"
                    r"start\s+(taking\s+)?[A-Z][A-Za-z-]+"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
        ]

    def validate(
        self,
        response_text: str,
        confidence_score: float,
        risk_level: ClassifiedRiskLevel | RiskLevel | str,
    ) -> OutputValidationResult:
        """Validate final response text before returning it to the user.

        Security contract: this validator is deterministic, local, and
        explainable. It checks for PHI leakage, unsafe medical claims,
        medication guidance, invalid confidence scores, and required
        disclaimers without calling an LLM or external service.
        """

        violations: list[str] = []
        violations.extend(self._matched_violations(response_text, self._phi_patterns))
        violations.extend(self._matched_violations(response_text, self._diagnosis_patterns))
        violations.extend(self._matched_violations(response_text, self._medication_patterns))

        if confidence_score < 0.0 or confidence_score > 1.0:
            violations.append("confidence_score_out_of_range")

        parsed_risk = self._parse_risk_level(risk_level)
        if parsed_risk in {
            ClassifiedRiskLevel.MEDIUM,
            ClassifiedRiskLevel.HIGH,
            ClassifiedRiskLevel.CRITICAL,
        } and not self._DISCLAIMER_PATTERN.search(response_text):
            violations.append("missing_required_disclaimer")

        if violations:
            return OutputValidationResult(
                validation_status=OutputValidationStatus.INVALID,
                violations=self._unique(violations),
            )

        return OutputValidationResult(
            validation_status=OutputValidationStatus.VALID,
            violations=[],
            corrected_response=response_text,
        )

    @staticmethod
    def _matched_violations(text: str, patterns: list[_ValidationPattern]) -> list[str]:
        return [validation.violation for validation in patterns if validation.pattern.search(text)]

    @staticmethod
    def _parse_risk_level(risk_level: ClassifiedRiskLevel | RiskLevel | str) -> ClassifiedRiskLevel | None:
        if isinstance(risk_level, ClassifiedRiskLevel):
            return risk_level

        value = risk_level.value if isinstance(risk_level, RiskLevel) else risk_level
        normalized_value = str(value).lower()

        try:
            return ClassifiedRiskLevel(normalized_value)
        except ValueError:
            return None

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        unique_items = []
        for item in items:
            if item not in unique_items:
                unique_items.append(item)
        return unique_items


def validate_output(
    response_text: str,
    confidence_score: float,
    risk_level: ClassifiedRiskLevel | RiskLevel | str,
) -> OutputValidationResult:
    """Validate output using the default deterministic validator."""

    return OutputValidator().validate(
        response_text=response_text,
        confidence_score=confidence_score,
        risk_level=risk_level,
    )
