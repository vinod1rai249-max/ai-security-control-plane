"""Analyze route orchestration for the security control plane."""

from datetime import UTC, datetime
from dataclasses import replace
from decimal import Decimal
import hashlib
from typing import Any
from uuid import UUID
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

try:
    from fastapi import APIRouter, Depends, Response
except ModuleNotFoundError:  # FastAPI is optional in the local test runtime.
    APIRouter = None
    Depends = None
    Response = None

from src.api.dependencies import (
    get_audit_logger,
    get_injection_detector,
    get_llm_client,
    get_llm_router,
    get_output_validator,
    get_phi_scrubber,
    get_policy_engine,
    get_risk_classifier,
)
from src.models.audit import AuditEvent
from src.models.requests import Domain, SecurityRequest
from src.models.responses import ProcessingDecision, RiskLevel, ValidationStatus
from src.services.audit_logger import AuditLogger
from src.services.injection_detector import InjectionDetector
from src.services.llm_client import LLMClient
from src.services.llm_router import LLMRouter
from src.services.output_validator import OutputValidator, OutputValidationStatus
from src.services.phi_scrubber import PHIScrubber
from src.services.policy_engine import PolicyDecision, PolicyEngine
from src.services.risk_classifier import ClassifiedRiskLevel, RiskClassifier


class AnalyzeResponse(BaseModel):
    """Safe response returned by the analyze endpoint."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    request_id: str
    session_id: str
    status: str
    answer: dict[str, str]
    risk_level: str
    decision: str
    use_llm: bool
    selected_model: str
    phi_detected: bool
    phi_entity_count: int = Field(ge=0)
    injection_detected: bool
    validation_status: str
    violations: list[str]
    audit_id: str | None
    reason: str


class PrecheckApiResponse(BaseModel):
    """Response returned before any LLM processing is allowed."""

    model_config = ConfigDict(extra="forbid")

    sanitized_query: str
    decision: str
    risk_level: str
    use_llm: bool
    selected_model: str
    blocked_reason: str | None
    audit_id: str | None


class PostcheckRequest(BaseModel):
    """Request body for validating an LLM response before delivery."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    session_id: UUID
    user_id: UUID
    llm_response: str
    risk_level: ClassifiedRiskLevel
    domain: Domain
    confidence_score: float = 1.0


class PostcheckApiResponse(BaseModel):
    """Response returned after output validation and audit logging."""

    model_config = ConfigDict(extra="forbid")

    validation_status: str
    violations: list[str]
    safe_response: str
    audit_id: str | None


def precheck_request(
    request: SecurityRequest,
    phi_scrubber: PHIScrubber | None = None,
    injection_detector: InjectionDetector | None = None,
    risk_classifier: RiskClassifier | None = None,
    policy_engine: PolicyEngine | None = None,
    llm_router: LLMRouter | None = None,
    audit_logger: AuditLogger | None = None,
) -> tuple[int, PrecheckApiResponse]:
    """Run deterministic pre-LLM checks and audit the routing decision."""

    phi_scrubber = phi_scrubber or get_phi_scrubber()
    injection_detector = injection_detector or get_injection_detector()
    risk_classifier = risk_classifier or get_risk_classifier()
    policy_engine = policy_engine or get_policy_engine()
    llm_router = llm_router or get_llm_router()
    audit_logger = audit_logger or get_audit_logger()

    scrub_result = phi_scrubber.scrub(request.query)
    injection_result = injection_detector.detect(scrub_result.sanitized_text)
    risk_result = risk_classifier.classify(scrub_result.sanitized_text)
    policy_result = policy_engine.evaluate(
        sanitized_query=scrub_result.sanitized_text,
        risk_level=risk_result.risk_level,
        flags=risk_result.flags,
        domain=request.domain,
        role=request.role,
    )

    decision = policy_result.decision
    blocked_reason = None
    if injection_result.is_injection:
        decision = PolicyDecision.BLOCK
        blocked_reason = f"Prompt injection detected: {injection_result.reason}"
    elif decision in {PolicyDecision.BLOCK, PolicyDecision.NEEDS_HUMAN_REVIEW}:
        blocked_reason = policy_result.reason

    route_decision = llm_router.route(
        risk_level=risk_result.risk_level,
        decision=decision,
        requires_human_review=decision == PolicyDecision.NEEDS_HUMAN_REVIEW,
    )
    audit_result = _write_audit_event(
        request=request,
        risk_level=risk_result.risk_level,
        decision=decision,
        selected_model=route_decision.selected_model,
        use_llm=route_decision.use_llm,
        validation_status=OutputValidationStatus.VALID,
        confidence_score=1.0,
        audit_logger=audit_logger,
    )
    if not audit_result.success:
        return 503, PrecheckApiResponse(
            sanitized_query="",
            decision=PolicyDecision.BLOCK.value,
            risk_level=risk_result.risk_level.value,
            use_llm=False,
            selected_model="none",
            blocked_reason=audit_result.error_message or "Audit write failed.",
            audit_id=None,
        )

    status_code = 200 if decision in {PolicyDecision.ALLOW, PolicyDecision.ALLOW_WITH_DISCLAIMER} else 403
    return status_code, PrecheckApiResponse(
        sanitized_query=scrub_result.sanitized_text,
        decision=decision.value,
        risk_level=risk_result.risk_level.value,
        use_llm=route_decision.use_llm,
        selected_model=route_decision.selected_model,
        blocked_reason=blocked_reason,
        audit_id=audit_result.audit_id,
    )


def postcheck_request(
    request: PostcheckRequest,
    output_validator: OutputValidator | None = None,
    audit_logger: AuditLogger | None = None,
) -> tuple[int, PostcheckApiResponse]:
    """Validate model output, audit the result, and fail closed on audit errors."""

    output_validator = output_validator or get_output_validator()
    audit_logger = audit_logger or get_audit_logger()

    validation = output_validator.validate(
        response_text=request.llm_response,
        confidence_score=request.confidence_score,
        risk_level=request.risk_level,
    )
    decision = (
        PolicyDecision.ALLOW
        if validation.validation_status == OutputValidationStatus.VALID
        else PolicyDecision.BLOCK
    )
    audit_request = SecurityRequest(
        request_id=request.request_id,
        session_id=request.session_id,
        user_id=request.user_id,
        query="[POSTCHECK_OUTPUT]",
        domain=request.domain,
        metadata={"source": "postcheck"},
    )
    audit_result = _write_audit_event(
        request=audit_request,
        risk_level=request.risk_level,
        decision=decision,
        selected_model="none",
        use_llm=False,
        validation_status=validation.validation_status,
        confidence_score=request.confidence_score,
        audit_logger=audit_logger,
    )
    if not audit_result.success:
        return 503, PostcheckApiResponse(
            validation_status=OutputValidationStatus.INVALID.value,
            violations=["audit_write_failed"],
            safe_response="",
            audit_id=None,
        )

    safe_response = request.llm_response if validation.validation_status == OutputValidationStatus.VALID else ""
    status_code = 200 if validation.validation_status == OutputValidationStatus.VALID else 422
    return status_code, PostcheckApiResponse(
        validation_status=validation.validation_status.value,
        violations=validation.violations,
        safe_response=safe_response,
        audit_id=audit_result.audit_id,
    )


def analyze_request(
    request: SecurityRequest,
    phi_scrubber: PHIScrubber | None = None,
    injection_detector: InjectionDetector | None = None,
    risk_classifier: RiskClassifier | None = None,
    policy_engine: PolicyEngine | None = None,
    llm_router: LLMRouter | None = None,
    llm_client: LLMClient | None = None,
    output_validator: OutputValidator | None = None,
    audit_logger: AuditLogger | None = None,
    llm_provider: Any | None = None,
) -> tuple[int, AnalyzeResponse]:
    """Run the approved deterministic analyze pipeline.

    Security contract: the raw query is accepted only at the boundary, scrubbed
    before downstream checks, never logged, never sent to an LLM, and never
    stored in audit records. The function fails closed when audit logging
    fails.
    """

    phi_scrubber = phi_scrubber or get_phi_scrubber()
    injection_detector = injection_detector or get_injection_detector()
    risk_classifier = risk_classifier or get_risk_classifier()
    policy_engine = policy_engine or get_policy_engine()
    llm_router = llm_router or get_llm_router()
    output_validator = output_validator or get_output_validator()
    audit_logger = audit_logger or get_audit_logger()

    scrub_result = phi_scrubber.scrub(request.query)
    injection_result = injection_detector.detect(scrub_result.sanitized_text)

    if injection_result.is_injection:
        risk_level = ClassifiedRiskLevel.HIGH
        decision = PolicyDecision.BLOCK
        route_decision = llm_router.route(risk_level, decision, requires_human_review=False)
        answer = _blocked_answer("Prompt injection detected. The request was blocked.")
        validation = output_validator.validate(
            _answer_to_validation_text(answer),
            confidence_score=1.0,
            risk_level=risk_level,
        )
        audit_result = _write_audit_event(
            request=request,
            risk_level=risk_level,
            decision=decision,
            selected_model=route_decision.selected_model,
            use_llm=route_decision.use_llm,
            validation_status=validation.validation_status,
            confidence_score=1.0,
            audit_logger=audit_logger,
        )
        if not audit_result.success:
            return _audit_failure_response(request, audit_result.error_message)
        return 403, _build_response(
            request=request,
            status="blocked",
            answer=answer,
            risk_level=risk_level,
            decision=decision,
            route_decision=route_decision,
            phi_entity_count=scrub_result.entity_count,
            injection_detected=True,
            validation_status=validation.validation_status.value,
            violations=validation.violations,
            audit_id=audit_result.audit_id,
            reason=injection_result.reason,
        )

    risk_result = risk_classifier.classify(scrub_result.sanitized_text)
    policy_result = policy_engine.evaluate(
        sanitized_query=scrub_result.sanitized_text,
        risk_level=risk_result.risk_level,
        flags=risk_result.flags,
        domain=request.domain,
        role=request.role,
    )
    requires_human_review = policy_result.decision == PolicyDecision.NEEDS_HUMAN_REVIEW
    route_decision = llm_router.route(
        risk_level=risk_result.risk_level,
        decision=policy_result.decision,
        requires_human_review=requires_human_review,
    )

    if policy_result.decision == PolicyDecision.BLOCK:
        answer = _blocked_answer(policy_result.reason)
        route_decision = replace(route_decision, selected_model="none")
        response_status = 403
        status = "blocked"
    elif requires_human_review:
        answer = _blocked_answer("This request requires human review before AI processing.")
        route_decision = replace(route_decision, selected_model="none")
        response_status = 202
        status = "needs_human_review"
    else:
        answer = fallback_safe_response()
        if route_decision.use_llm and _can_call_llm(
            policy_result.decision,
            risk_result.risk_level,
            injection_detected=False,
        ):
            try:
                active_llm_client = llm_client or llm_provider or get_llm_client()
                answer, selected_model = _generate_llm_answer(
                    llm_client=active_llm_client,
                    sanitized_query=scrub_result.sanitized_text,
                    domain=request.domain.value,
                )
                route_decision = replace(route_decision, selected_model=selected_model)
            except Exception:
                answer = fallback_safe_response()
                route_decision = replace(route_decision, use_llm=False, selected_model="fallback")
        else:
            route_decision = replace(route_decision, selected_model="none")
        response_status = 200
        status = "ok"

    validation = output_validator.validate(
        response_text=_answer_to_validation_text(answer),
        confidence_score=0.9,
        risk_level=risk_result.risk_level,
    )
    if validation.validation_status != OutputValidationStatus.VALID:
        answer = _blocked_answer("Output validation failed. The response was blocked.")
        status = "blocked"
        response_status = 503

    audit_result = _write_audit_event(
        request=request,
        risk_level=risk_result.risk_level,
        decision=policy_result.decision,
        selected_model=route_decision.selected_model,
        use_llm=route_decision.use_llm,
        validation_status=validation.validation_status,
        confidence_score=0.9,
        audit_logger=audit_logger,
    )
    if not audit_result.success:
        return _audit_failure_response(request, audit_result.error_message)

    return response_status, _build_response(
        request=request,
        status=status,
        answer=answer,
        risk_level=risk_result.risk_level,
        decision=policy_result.decision,
        route_decision=route_decision,
        phi_entity_count=scrub_result.entity_count,
        injection_detected=False,
        validation_status=validation.validation_status.value,
        violations=validation.violations,
        audit_id=audit_result.audit_id,
        reason=policy_result.reason,
    )


def fallback_safe_response() -> dict[str, str]:
    return {
        "summary": "This appears to be a general health-related question.",
        "safety_assessment": "No immediate policy or security risks were detected.",
        "recommendation": "You may review general educational material.",
        "disclaimer": "For personalized medical advice, please consult a healthcare provider.",
    }


def _placeholder_answer(use_llm: bool, disclaimer: str | None) -> dict[str, str]:
    return fallback_safe_response()


def _blocked_answer(reason: str) -> dict[str, str]:
    return {
        "summary": "The request was blocked by the safety pipeline.",
        "safety_assessment": reason,
        "recommendation": "Revise the request or consult a healthcare provider for clinical guidance.",
        "disclaimer": _standard_disclaimer(None),
    }


def _standard_disclaimer(disclaimer: str | None) -> str:
    return disclaimer or "For personalized medical advice, please consult a healthcare provider."


def _answer_to_validation_text(answer: dict[str, str]) -> str:
    return " ".join(answer.values())


def _can_call_llm(
    decision: PolicyDecision,
    risk_level: ClassifiedRiskLevel,
    injection_detected: bool,
) -> bool:
    return (
        decision in {PolicyDecision.ALLOW, PolicyDecision.ALLOW_WITH_DISCLAIMER}
        and risk_level in {ClassifiedRiskLevel.LOW, ClassifiedRiskLevel.MEDIUM}
        and not injection_detected
    )


def _generate_llm_answer(llm_client: Any, sanitized_query: str, domain: str) -> tuple[dict[str, str], str]:
    if hasattr(llm_client, "generate_response"):
        return llm_client.generate_response(sanitized_query), getattr(llm_client, "model", "unknown")

    legacy_result = llm_client.generate(sanitized_query=sanitized_query, domain=domain)
    if not legacy_result.success:
        raise RuntimeError(legacy_result.error_message or "LLM provider failed.")
    return {
        "summary": legacy_result.text,
        "safety_assessment": "The request passed deterministic safety checks before LLM routing.",
        "recommendation": "Use this as a general educational explanation only.",
        "disclaimer": _standard_disclaimer(None),
    }, legacy_result.model


def _write_audit_event(
    request: SecurityRequest,
    risk_level: ClassifiedRiskLevel,
    decision: PolicyDecision,
    selected_model: str,
    use_llm: bool,
    validation_status: OutputValidationStatus,
    confidence_score: float,
    audit_logger: AuditLogger,
):
    timestamp_utc = datetime.now(UTC)
    audit_confidence_score = min(1.0, max(0.0, confidence_score))
    event = AuditEvent(
        request_id=request.request_id,
        session_id=request.session_id,
        timestamp=timestamp_utc,
        timestamp_utc=timestamp_utc,
        user_id=request.user_id,
        domain=request.domain,
        risk_level=_to_audit_risk_level(risk_level),
        decision=_to_audit_decision(decision),
        query_hash=_hash_query(request.query),
        use_llm=use_llm,
        selected_model=selected_model,
        model_used=selected_model,
        prompt_version="deterministic-placeholder-v1",
        tokens_used=0,
        cost=Decimal("0"),
        validation_status=_to_audit_validation_status(validation_status),
        confidence_score=audit_confidence_score,
    )
    return audit_logger.log(event)


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _to_audit_risk_level(risk_level: ClassifiedRiskLevel) -> RiskLevel:
    return RiskLevel(risk_level.value.upper())


def _to_audit_decision(decision: PolicyDecision) -> ProcessingDecision:
    if decision in {PolicyDecision.BLOCK, PolicyDecision.NEEDS_HUMAN_REVIEW}:
        return ProcessingDecision.BLOCK if decision == PolicyDecision.BLOCK else ProcessingDecision.HUMAN_REVIEW
    return ProcessingDecision.ALLOW


def _to_audit_validation_status(validation_status: OutputValidationStatus) -> ValidationStatus:
    if validation_status == OutputValidationStatus.VALID:
        return ValidationStatus.PASSED
    if validation_status == OutputValidationStatus.REQUIRES_REVIEW:
        return ValidationStatus.SANITIZED
    return ValidationStatus.FAILED


def _audit_failure_response(
    request: SecurityRequest,
    error_message: str | None,
) -> tuple[int, AnalyzeResponse]:
    return 503, AnalyzeResponse(
        response_id=str(uuid4()),
        request_id=str(request.request_id),
        session_id=str(request.session_id),
        status="audit_failed",
        answer={
            "summary": "The request was blocked by the safety pipeline.",
            "safety_assessment": "Audit logging failed, so the request failed closed.",
            "recommendation": "Try again later or consult a healthcare provider for clinical guidance.",
            "disclaimer": _standard_disclaimer(None),
        },
        risk_level="unknown",
        decision="block",
        use_llm=False,
        selected_model="none",
        phi_detected=False,
        phi_entity_count=0,
        injection_detected=False,
        validation_status="invalid",
        violations=["audit_write_failed"],
        audit_id=None,
        reason=error_message or "Audit write failed.",
    )


def _build_response(
    request: SecurityRequest,
    status: str,
    answer: dict[str, str],
    risk_level: ClassifiedRiskLevel,
    decision: PolicyDecision,
    route_decision: Any,
    phi_entity_count: int,
    injection_detected: bool,
    validation_status: str,
    violations: list[str],
    audit_id: str | None,
    reason: str,
) -> AnalyzeResponse:
    return AnalyzeResponse(
        response_id=str(uuid4()),
        request_id=str(request.request_id),
        session_id=str(request.session_id),
        status=status,
        answer=answer,
        risk_level=risk_level.value,
        decision=decision.value,
        use_llm=route_decision.use_llm,
        selected_model=route_decision.selected_model,
        phi_detected=phi_entity_count > 0,
        phi_entity_count=phi_entity_count,
        injection_detected=injection_detected,
        validation_status=validation_status,
        violations=violations,
        audit_id=audit_id,
        reason=reason,
    )


if APIRouter is not None:
    router = APIRouter(prefix="/v1", tags=["analyze"])

    @router.post("/analyze", response_model=AnalyzeResponse)
    def analyze(
        request: SecurityRequest,
        response: Response,
        phi_scrubber: PHIScrubber = Depends(get_phi_scrubber),
        injection_detector: InjectionDetector = Depends(get_injection_detector),
        risk_classifier: RiskClassifier = Depends(get_risk_classifier),
        policy_engine: PolicyEngine = Depends(get_policy_engine),
        llm_router: LLMRouter = Depends(get_llm_router),
        output_validator: OutputValidator = Depends(get_output_validator),
        audit_logger: AuditLogger = Depends(get_audit_logger),
    ) -> AnalyzeResponse:
        status_code, analyze_response = analyze_request(
            request=request,
            phi_scrubber=phi_scrubber,
            injection_detector=injection_detector,
            risk_classifier=risk_classifier,
            policy_engine=policy_engine,
            llm_router=llm_router,
            output_validator=output_validator,
            audit_logger=audit_logger,
        )
        response.status_code = status_code
        return analyze_response

    @router.post("/precheck", response_model=PrecheckApiResponse)
    def precheck(
        request: SecurityRequest,
        response: Response,
        phi_scrubber: PHIScrubber = Depends(get_phi_scrubber),
        injection_detector: InjectionDetector = Depends(get_injection_detector),
        risk_classifier: RiskClassifier = Depends(get_risk_classifier),
        policy_engine: PolicyEngine = Depends(get_policy_engine),
        llm_router: LLMRouter = Depends(get_llm_router),
        audit_logger: AuditLogger = Depends(get_audit_logger),
    ) -> PrecheckApiResponse:
        status_code, precheck_response = precheck_request(
            request=request,
            phi_scrubber=phi_scrubber,
            injection_detector=injection_detector,
            risk_classifier=risk_classifier,
            policy_engine=policy_engine,
            llm_router=llm_router,
            audit_logger=audit_logger,
        )
        response.status_code = status_code
        return precheck_response

    @router.post("/postcheck", response_model=PostcheckApiResponse)
    def postcheck(
        request: PostcheckRequest,
        response: Response,
        output_validator: OutputValidator = Depends(get_output_validator),
        audit_logger: AuditLogger = Depends(get_audit_logger),
    ) -> PostcheckApiResponse:
        status_code, postcheck_response = postcheck_request(
            request=request,
            output_validator=output_validator,
            audit_logger=audit_logger,
        )
        response.status_code = status_code
        return postcheck_response
else:
    router = None
