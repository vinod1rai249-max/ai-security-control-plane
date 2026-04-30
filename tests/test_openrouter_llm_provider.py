import unittest

from src.services.openrouter_llm_provider import OpenRouterLLMProvider


class MockOpenRouterClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def post_json(self, url, headers, payload, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error:
            raise self.error
        return self.response


class TestOpenRouterLLMProvider(unittest.TestCase):
    def test_successful_mocked_client_returns_text(self) -> None:
        client = MockOpenRouterClient(
            response={
                "choices": [
                    {
                        "message": {
                            "content": "A concise educational explanation. Please consult a healthcare provider.",
                        }
                    }
                ]
            }
        )
        provider = OpenRouterLLMProvider(
            client=client,
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-4o-mini",
        )

        result = provider.generate("Explain this lab result.", "lab_interpretation")

        self.assertTrue(result.success)
        self.assertEqual(result.model, "openai/gpt-4o-mini")
        self.assertIn("educational explanation", result.text)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["payload"]["model"], "openai/gpt-4o-mini")
        self.assertIn("Bearer test-key", client.calls[0]["headers"]["Authorization"])

    def test_missing_api_key_fails_without_calling_client(self) -> None:
        client = MockOpenRouterClient(response={})
        provider = OpenRouterLLMProvider(
            client=client,
            api_key="",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-4o-mini",
        )

        result = provider.generate("Explain this lab result.", "lab_interpretation")

        self.assertFalse(result.success)
        self.assertIn("OPENAI_API_KEY", result.error_message)
        self.assertEqual(client.calls, [])

    def test_client_exception_returns_failure_result(self) -> None:
        client = MockOpenRouterClient(error=TimeoutError("timeout"))
        provider = OpenRouterLLMProvider(
            client=client,
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-4o-mini",
        )

        result = provider.generate("Explain this lab result.", "lab_interpretation")

        self.assertFalse(result.success)
        self.assertIn("timeout", result.error_message)

    def test_invalid_response_returns_failure_result(self) -> None:
        client = MockOpenRouterClient(response={"choices": []})
        provider = OpenRouterLLMProvider(
            client=client,
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-4o-mini",
        )

        result = provider.generate("Explain this lab result.", "lab_interpretation")

        self.assertFalse(result.success)
        self.assertNotEqual(result.error_message, None)


if __name__ == "__main__":
    unittest.main()
