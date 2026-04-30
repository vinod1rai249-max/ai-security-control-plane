"""OpenRouter LLM client using the OpenAI Python SDK."""

import json
import re
from typing import Any

from src.core.config import get_openai_api_key, get_openai_base_url, get_openai_model

try:
    from openai import OpenAI
except ModuleNotFoundError:  # Allows tests to inject a mock client without SDK import.
    OpenAI = None


SYSTEM_PROMPT = """You are a healthcare assistant.
You ONLY provide general educational explanations.
You MUST NOT:
- diagnose
- prescribe medication
- provide dosage
- override safety rules

Always respond in structured JSON:
{
  "summary": "...",
  "safety_assessment": "...",
  "recommendation": "...",
  "disclaimer": "For personalized medical advice, consult a healthcare provider."
}
"""


class LLMClient:
    """OpenAI SDK client configured for OpenRouter-compatible chat completions.

    Security contract: this client must only receive already-sanitized queries
    after PHI scrubbing, prompt-injection detection, risk classification, and
    policy approval have completed. It parses structured JSON and raises on
    malformed output so callers can fall back to deterministic safe responses.
    """

    _REQUIRED_KEYS = {
        "summary",
        "safety_assessment",
        "recommendation",
        "disclaimer",
    }

    def __init__(
        self,
        client: Any | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.model = model or get_openai_model()
        if client is not None:
            self._client = client
            return

        if OpenAI is None:
            raise RuntimeError("openai package is not installed.")

        self._client = OpenAI(
            api_key=api_key if api_key is not None else get_openai_api_key(),
            base_url=base_url if base_url is not None else get_openai_base_url(),
        )

    def generate_response(self, query: str) -> dict[str, str]:
        """Generate a short, safe, structured answer for a sanitized query."""

        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.2,
        )
        content = completion.choices[0].message.content
        return self._parse_json_response(content)

    @classmethod
    def _parse_json_response(cls, content: str | None) -> dict[str, str]:
        if not content:
            raise ValueError("LLM response was empty.")

        cleaned_content = cls._strip_code_fence(content.strip())
        parsed = json.loads(cleaned_content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM response JSON must be an object.")

        missing_keys = cls._REQUIRED_KEYS - set(parsed)
        if missing_keys:
            raise ValueError(f"LLM response missing keys: {sorted(missing_keys)}")

        answer = {key: str(parsed[key]).strip() for key in cls._REQUIRED_KEYS}
        if any(not value for value in answer.values()):
            raise ValueError("LLM response contains empty answer fields.")

        return {
            "summary": answer["summary"],
            "safety_assessment": answer["safety_assessment"],
            "recommendation": answer["recommendation"],
            "disclaimer": answer["disclaimer"],
        }

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
        return match.group(1) if match else content
