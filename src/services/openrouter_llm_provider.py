"""OpenRouter-compatible LLM provider with deterministic fallback support."""

from dataclasses import dataclass
import json
import os
from typing import Any, Protocol
from urllib import request
from urllib.error import URLError


@dataclass(frozen=True)
class LLMProviderResult:
    """Result returned by an optional LLM provider call."""

    success: bool
    text: str
    model: str
    error_message: str | None = None


class LLMHttpClient(Protocol):
    """Minimal HTTP client protocol used to keep tests fully mocked."""

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        ...


class UrllibLLMHttpClient:
    """Small stdlib HTTP client for OpenAI-compatible chat completions."""

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=url,
            data=body,
            headers=headers,
            method="POST",
        )
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


class OpenRouterLLMProvider:
    """Optional OpenRouter provider for already-approved de-identified prompts.

    Security contract: callers must run PHI scrubbing, prompt injection
    detection, risk classification, and policy routing before calling this
    provider. This class never decides whether a request is safe; it only
    attempts a provider call and returns an explicit failure result so callers
    can fall back deterministically.
    """

    def __init__(
        self,
        client: LLMHttpClient | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._client = client or UrllibLLMHttpClient()
        self._api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self._base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        self._model = model or os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini")

    @property
    def model(self) -> str:
        return self._model

    def generate(self, sanitized_query: str, domain: str, timeout_seconds: int = 20) -> LLMProviderResult:
        """Generate an educational answer for an approved sanitized query."""

        if not self._api_key:
            return LLMProviderResult(
                success=False,
                text="",
                model=self._model,
                error_message="OPENAI_API_KEY is not configured.",
            )

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You provide concise, general educational healthcare explanations. "
                        "Do not diagnose, prescribe, or include patient identifiers. "
                        "Always remind users to consult a healthcare provider."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Domain: {domain}\nSanitized question: {sanitized_query}",
                },
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            data = self._client.post_json(
                url=f"{self._base_url.rstrip('/')}/chat/completions",
                headers=headers,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
            text = self._extract_text(data)
        except (IndexError, KeyError, TypeError, ValueError, URLError, TimeoutError, OSError) as exc:
            return LLMProviderResult(
                success=False,
                text="",
                model=self._model,
                error_message=str(exc),
            )

        if not text:
            return LLMProviderResult(
                success=False,
                text="",
                model=self._model,
                error_message="Provider returned an empty response.",
            )

        return LLMProviderResult(
            success=True,
            text=text,
            model=self._model,
            error_message=None,
        )

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        choices = data["choices"]
        first_choice = choices[0]
        message = first_choice["message"]
        content = message["content"]
        return str(content).strip()
