"""Deterministic prompt injection detector."""

from dataclasses import dataclass
import re
from typing import Pattern


@dataclass(frozen=True)
class InjectionDetectionResult:
    """Explainable result from prompt injection detection."""

    is_injection: bool
    confidence_score: float
    detected_patterns: list[str]
    reason: str


@dataclass(frozen=True)
class _InjectionPattern:
    name: str
    reason: str
    confidence_score: float
    pattern: Pattern[str]


class InjectionDetector:
    """Detects prompt injection attempts with local deterministic rules."""

    def __init__(self) -> None:
        self._patterns = [
            _InjectionPattern(
                name="ignore_previous_instructions",
                reason="Prompt attempts to discard prior or governing instructions.",
                confidence_score=0.95,
                pattern=re.compile(
                    r"\b(ignore|disregard|forget)\s+"
                    r"(all\s+)?(previous|prior|above|earlier)\s+"
                    r"(instructions|rules|directions|messages)\b",
                    re.IGNORECASE,
                ),
            ),
            _InjectionPattern(
                name="reveal_system_prompt",
                reason="Prompt attempts to reveal hidden system or developer instructions.",
                confidence_score=0.95,
                pattern=re.compile(
                    r"\b("
                    r"reveal|show|print|display|output|dump"
                    r")\s+(the\s+)?"
                    r"(system\s+prompt|developer\s+message|hidden\s+instructions|initial\s+instructions)\b",
                    re.IGNORECASE,
                ),
            ),
            _InjectionPattern(
                name="bypass_safety_rules",
                reason="Prompt attempts to bypass safety or policy rules.",
                confidence_score=0.92,
                pattern=re.compile(
                    r"\b("
                    r"bypass|disable|override|ignore"
                    r")\s+(all\s+)?"
                    r"(safety|security|policy|guardrail|guardrails|rules|restrictions)\b",
                    re.IGNORECASE,
                ),
            ),
            _InjectionPattern(
                name="unrestricted_model_request",
                reason="Prompt attempts to make the model act without restrictions.",
                confidence_score=0.9,
                pattern=re.compile(
                    r"\b("
                    r"act\s+as|pretend\s+to\s+be|roleplay\s+as"
                    r")\s+(an?\s+)?"
                    r"(unrestricted|uncensored|unfiltered|unlimited|jailbroken)\s+"
                    r"(model|ai|assistant|chatbot)\b",
                    re.IGNORECASE,
                ),
            ),
            _InjectionPattern(
                name="developer_or_system_override",
                reason="Prompt attempts to create a fake system or developer override.",
                confidence_score=0.93,
                pattern=re.compile(
                    r"\b("
                    r"system\s*override|developer\s*override|new\s+system\s+message|"
                    r"new\s+developer\s+instruction|you\s+are\s+now\s+in\s+developer\s+mode"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
            _InjectionPattern(
                name="hidden_instruction_attempt",
                reason="Prompt contains hidden or out-of-band instruction markers.",
                confidence_score=0.88,
                pattern=re.compile(
                    r"\b("
                    r"hidden\s+instruction|secret\s+instruction|do\s+not\s+tell\s+the\s+user|"
                    r"invisible\s+instruction|between\s+the\s+tags"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
            _InjectionPattern(
                name="jailbreak_request",
                reason="Prompt uses known jailbreak language.",
                confidence_score=0.94,
                pattern=re.compile(
                    r"\b("
                    r"jailbreak|dan\s+mode|do\s+anything\s+now|developer\s+mode|"
                    r"break\s+character|ignore\s+openai\s+policy"
                    r")\b",
                    re.IGNORECASE,
                ),
            ),
        ]

    def detect(self, text: str) -> InjectionDetectionResult:
        """Return deterministic prompt injection detection for the supplied text.

        Security contract: this method performs only local pattern checks. It
        does not call an LLM, does not log prompt content, and returns the
        matched rule names so callers can explain why a request was blocked.
        """

        matches = [pattern for pattern in self._patterns if pattern.pattern.search(text)]

        if not matches:
            return InjectionDetectionResult(
                is_injection=False,
                confidence_score=0.0,
                detected_patterns=[],
                reason="No deterministic prompt injection patterns were detected.",
            )

        return InjectionDetectionResult(
            is_injection=True,
            confidence_score=max(pattern.confidence_score for pattern in matches),
            detected_patterns=[pattern.name for pattern in matches],
            reason=self._build_reason(matches),
        )

    @staticmethod
    def _build_reason(matches: list[_InjectionPattern]) -> str:
        if len(matches) == 1:
            return matches[0].reason

        return "Multiple prompt injection patterns detected: " + ", ".join(
            pattern.reason for pattern in matches
        )


def detect_injection(text: str) -> InjectionDetectionResult:
    """Detect prompt injection using the default deterministic detector."""

    return InjectionDetector().detect(text)
