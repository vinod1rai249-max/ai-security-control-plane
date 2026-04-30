"""Deterministic risk classifier for clinical AI requests."""

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Pattern


class ClassifiedRiskLevel(StrEnum):
    """Risk levels returned by the rule-based classifier."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class RiskClassification:
    """Explainable result from deterministic risk classification."""

    risk_level: ClassifiedRiskLevel
    reason: str
    flags: list[str]


@dataclass(frozen=True)
class _Rule:
    risk_level: ClassifiedRiskLevel
    flag: str
    reason: str
    pattern: Pattern[str]


class RiskClassifier:
    """Classifies request risk using fast, explainable rules only."""

    def __init__(self) -> None:
        self._rules = [
            _Rule(
                ClassifiedRiskLevel.CRITICAL,
                "emergency_intent",
                "Emergency intent or life-threatening symptoms require immediate human review.",
                re.compile(
                    r"\b("
                    r"emergency|er|911|ambulance|life[-\s]?threatening|"
                    r"cannot breathe|can't breathe|chest pain|stroke|seizure|"
                    r"unconscious|suicidal|overdose|severe bleeding"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
            _Rule(
                ClassifiedRiskLevel.HIGH,
                "diagnosis_intent",
                "Diagnosis intent requires high-risk handling.",
                re.compile(
                    r"\b("
                    r"diagnose|diagnosis|do i have|does this mean i have|"
                    r"what disease|what condition|am i sick with"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
            _Rule(
                ClassifiedRiskLevel.HIGH,
                "medication_suggestion",
                "Medication suggestions require high-risk handling.",
                re.compile(
                    r"\b("
                    r"medication|medicine|prescribe|prescription|dosage|dose|"
                    r"should i take|can i take|drug"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
            _Rule(
                ClassifiedRiskLevel.MEDIUM,
                "interpretation_request",
                "Interpretation requests require medium-risk handling.",
                re.compile(
                    r"\b("
                    r"is this normal|normal or abnormal|interpret|interpretation|"
                    r"what does this mean|should i be concerned|concerning"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
            _Rule(
                ClassifiedRiskLevel.LOW,
                "lab_explanation",
                "Lab explanations are low risk when no higher-risk intent is present.",
                re.compile(
                    r"\b("
                    r"lab explanation|explain.*lab|lab result|blood test|"
                    r"cbc|a1c|cholesterol|reference range"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
            _Rule(
                ClassifiedRiskLevel.LOW,
                "general_health_question",
                "General health education is low risk when no higher-risk intent is present.",
                re.compile(
                    r"\b("
                    r"general health|healthy diet|exercise|hydration|sleep|"
                    r"what is|how does|explain"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
        ]

    def classify(self, text: str) -> RiskClassification:
        """Return the highest matched risk level for the request text.

        Security contract: this classifier is deterministic, local, and
        explainable. It does not call an LLM or any external service. Higher
        risk triggers always take precedence over lower risk triggers.
        """

        critical_lab = self._critical_lab_result(text)
        if critical_lab is not None:
            return critical_lab

        matches = [rule for rule in self._rules if rule.pattern.search(text)]
        if not matches:
            return RiskClassification(
                risk_level=ClassifiedRiskLevel.LOW,
                reason="No medium, high, or critical risk triggers were detected.",
                flags=[],
            )

        selected_level = self._highest_risk_level(matches)
        selected_matches = [rule for rule in matches if rule.risk_level == selected_level]
        flags = self._unique_flags(selected_matches)
        reason = selected_matches[0].reason

        return RiskClassification(
            risk_level=selected_level,
            reason=reason,
            flags=flags,
        )

    def _critical_lab_result(self, text: str) -> RiskClassification | None:
        lowered_text = text.lower()
        lab_checks = [
            ("potassium", "critical_potassium", lambda value: value >= 6.5, "Very high potassium requires provider escalation."),
            ("inr", "critical_inr", lambda value: value >= 5.0, "Very high INR requires provider escalation."),
            ("glucose", "critical_glucose", lambda value: value >= 400.0 or value <= 50.0, "Extremely abnormal glucose requires provider escalation."),
            ("egfr", "critical_egfr", lambda value: value < 15.0, "Very low eGFR requires provider escalation."),
            ("creatinine", "critical_creatinine", lambda value: value >= 5.0, "Very high creatinine requires provider escalation."),
        ]
        for lab_name, flag, predicate, reason in lab_checks:
            value = self._extract_lab_value(lowered_text, lab_name)
            if value is not None and predicate(value):
                return RiskClassification(
                    risk_level=ClassifiedRiskLevel.CRITICAL,
                    reason=reason,
                    flags=[flag],
                )

        lab_keywords = {
            "hba1c": "lab_explanation",
            "a1c": "lab_explanation",
            "ldl": "lab_explanation",
            "hdl": "lab_explanation",
            "glucose": "lab_explanation",
            "creatinine": "lab_explanation",
            "potassium": "lab_explanation",
            "inr": "lab_explanation",
            "egfr": "lab_explanation",
        }
        interpretation_terms = [
            "is this normal",
            "normal or abnormal",
            "interpret",
            "interpretation",
            "what does this mean",
            "should i be concerned",
            "concerning",
        ]
        if any(keyword in lowered_text for keyword in lab_keywords) and not any(
            term in lowered_text for term in interpretation_terms
        ):
            return RiskClassification(
                risk_level=ClassifiedRiskLevel.LOW,
                reason="Supported lab value explanation is low risk when no critical threshold is present.",
                flags=["lab_explanation"],
            )

        return None

    @staticmethod
    def _extract_lab_value(text: str, lab_name: str) -> float | None:
        patterns = [
            rf"\b{re.escape(lab_name)}\b[^\d<>-]*(?:is|=|:)?\s*(?:<|>)?\s*(-?\d+(?:\.\d+)?)",
            rf"(-?\d+(?:\.\d+)?)\s*(?:mg/dl|mmol/l|ml/min|seconds)?\s*\b{re.escape(lab_name)}\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))
        return None

    @staticmethod
    def _highest_risk_level(rules: list[_Rule]) -> ClassifiedRiskLevel:
        rank = {
            ClassifiedRiskLevel.LOW: 1,
            ClassifiedRiskLevel.MEDIUM: 2,
            ClassifiedRiskLevel.HIGH: 3,
            ClassifiedRiskLevel.CRITICAL: 4,
        }
        return max((rule.risk_level for rule in rules), key=lambda level: rank[level])

    @staticmethod
    def _unique_flags(rules: list[_Rule]) -> list[str]:
        flags = []
        for rule in rules:
            if rule.flag not in flags:
                flags.append(rule.flag)
        return flags


def classify_risk(text: str) -> RiskClassification:
    """Classify request risk using the default deterministic classifier."""

    return RiskClassifier().classify(text)
