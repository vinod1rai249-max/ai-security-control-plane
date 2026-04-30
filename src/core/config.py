"""Environment configuration for the AI Security Control Plane."""

import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None


def load_environment() -> None:
    """Load local .env values when python-dotenv is installed."""

    if load_dotenv is not None:
        load_dotenv()


def get_openai_api_key() -> str | None:
    load_environment()
    return os.getenv("OPENAI_API_KEY")


def get_openai_base_url() -> str | None:
    load_environment()
    return os.getenv("OPENAI_BASE_URL")


def get_openai_model() -> str:
    load_environment()
    return os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini")
