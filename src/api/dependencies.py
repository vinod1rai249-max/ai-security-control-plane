"""Dependency factories for API route orchestration."""

from src.services.audit_logger import AuditLogger
from src.services.injection_detector import InjectionDetector
from src.services.llm_client import LLMClient
from src.services.llm_router import LLMRouter
from src.services.openrouter_llm_provider import OpenRouterLLMProvider
from src.services.output_validator import OutputValidator
from src.services.phi_scrubber import PHIScrubber
from src.services.policy_engine import PolicyEngine
from src.services.risk_classifier import RiskClassifier


def get_phi_scrubber() -> PHIScrubber:
    return PHIScrubber()


def get_injection_detector() -> InjectionDetector:
    return InjectionDetector()


def get_risk_classifier() -> RiskClassifier:
    return RiskClassifier()


def get_policy_engine() -> PolicyEngine:
    return PolicyEngine()


def get_llm_router() -> LLMRouter:
    return LLMRouter()


def get_llm_client() -> LLMClient:
    return LLMClient()


def get_openrouter_llm_provider() -> OpenRouterLLMProvider:
    return OpenRouterLLMProvider()


def get_output_validator() -> OutputValidator:
    return OutputValidator()


def get_audit_logger() -> AuditLogger:
    return AuditLogger()
