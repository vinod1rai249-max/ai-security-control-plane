"""PHI scrubbing service for de-identifying clinical text."""

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Pattern


class PHIEntityType(StrEnum):
    """PHI entity types scrubbed by this service."""

    NAME = "NAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    MRN = "MRN"
    INSURANCE_ID = "INSURANCE_ID"


@dataclass(frozen=True)
class ScrubResult:
    """Result returned after PHI has been removed from text."""

    sanitized_text: str
    entity_count: int
    entity_types: list[str]
    token_map: dict[str, str]


@dataclass(frozen=True)
class _PatternSpec:
    entity_type: PHIEntityType
    pattern: Pattern[str]
    group: int = 0


@dataclass(frozen=True)
class _Match:
    entity_type: PHIEntityType
    start: int
    end: int
    value: str


class PHIScrubber:
    """Scrubs raw PHI before any downstream security or model processing."""

    def __init__(self) -> None:
        self._patterns = [
            _PatternSpec(
                PHIEntityType.EMAIL,
                re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
            ),
            _PatternSpec(
                PHIEntityType.PHONE,
                re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"),
            ),
            _PatternSpec(
                PHIEntityType.MRN,
                re.compile(
                    r"\b(?:MRN|Medical Record(?: Number)?|Medical Record No\.?)"
                    r"\s*[:#-]?\s*([A-Z]{0,3}\d{6,10})\b",
                    re.IGNORECASE,
                ),
                group=1,
            ),
            _PatternSpec(
                PHIEntityType.INSURANCE_ID,
                re.compile(
                    r"\b(?:Insurance(?: ID| Number)?|Policy(?: ID| Number)?)"
                    r"\s*[:#-]?\s*([A-Z]{2,5}[- ]?\d{6,12}|[A-Z0-9]{8,16})\b",
                    re.IGNORECASE,
                ),
                group=1,
            ),
            _PatternSpec(
                PHIEntityType.NAME,
                re.compile(
                    r"\b(?:Patient|Name|Member)\s*(?:Name)?\s*[:#-]?\s*"
                    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b"
                ),
                group=1,
            ),
            _PatternSpec(
                PHIEntityType.NAME,
                re.compile(r"\b(?:Mr|Ms|Mrs|Dr)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b"),
                group=1,
            ),
        ]

    def scrub(self, text: str) -> ScrubResult:
        """Return de-identified text and an in-memory token map without persistence.

        Security contract: this method accepts raw PHI, replaces supported PHI
        values with typed tokens, and returns the original values only in the
        ephemeral token_map for the caller to handle within the request scope.
        It does not log, persist, call an LLM, or call external services.
        """

        matches = self._find_matches(text)
        token_map: dict[str, str] = {}
        type_counts: dict[PHIEntityType, int] = {}
        replacements: list[tuple[int, int, str]] = []

        for match in matches:
            next_count = type_counts.get(match.entity_type, 0) + 1
            type_counts[match.entity_type] = next_count
            token = f"[PHI_{match.entity_type.value}_{next_count:03d}]"
            token_map[token] = match.value
            replacements.append((match.start, match.end, token))

        sanitized_text = text
        for start, end, token in reversed(replacements):
            sanitized_text = sanitized_text[:start] + token + sanitized_text[end:]

        entity_types = []
        for match in matches:
            entity_type = match.entity_type.value
            if entity_type not in entity_types:
                entity_types.append(entity_type)

        return ScrubResult(
            sanitized_text=sanitized_text,
            entity_count=len(matches),
            entity_types=entity_types,
            token_map=token_map,
        )

    def _find_matches(self, text: str) -> list[_Match]:
        matches: list[_Match] = []

        for spec in self._patterns:
            for raw_match in spec.pattern.finditer(text):
                start, end = raw_match.span(spec.group)
                start, end = self._trim_span(text, start, end)
                value = text[start:end]

                if value and not self._overlaps_existing_match(start, end, matches):
                    matches.append(_Match(spec.entity_type, start, end, value))

        return sorted(matches, key=lambda match: match.start)

    @staticmethod
    def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        return start, end

    @staticmethod
    def _overlaps_existing_match(start: int, end: int, matches: list[_Match]) -> bool:
        for existing_match in matches:
            if start < existing_match.end and end > existing_match.start:
                return True
        return False


def scrub_phi(text: str) -> ScrubResult:
    """Scrub supported PHI types from text using the default PHI scrubber."""

    return PHIScrubber().scrub(text)
