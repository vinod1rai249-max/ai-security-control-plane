"""Application entrypoint for the AI Security Control Plane."""

try:
    from fastapi import FastAPI, Response
except ModuleNotFoundError:
    FastAPI = None
    Response = None

from src.api.routes.analyze import (
    AnalyzeResponse,
    PostcheckApiResponse,
    PostcheckRequest,
    PrecheckApiResponse,
    analyze_request,
    postcheck_request,
    precheck_request,
    router as analyze_router,
)
from src.core.config import load_environment
from src.models.requests import SecurityRequest


def create_app():
    """Create the FastAPI app when FastAPI is installed."""

    load_environment()

    if FastAPI is None:
        return None

    app = FastAPI(title="AI Security Control Plane")
    if analyze_router is not None:
        app.include_router(analyze_router)

    @app.post("/analyze", response_model=AnalyzeResponse)
    def analyze_root(request: SecurityRequest, response: Response) -> AnalyzeResponse:
        """Compatibility endpoint for local demo clients."""

        status_code, analyze_response = analyze_request(request)
        response.status_code = status_code
        return analyze_response

    @app.post("/precheck", response_model=PrecheckApiResponse)
    def precheck_root(request: SecurityRequest, response: Response) -> PrecheckApiResponse:
        """Run the deterministic pre-LLM control-plane checks."""

        status_code, precheck_response = precheck_request(request)
        response.status_code = status_code
        return precheck_response

    @app.post("/postcheck", response_model=PostcheckApiResponse)
    def postcheck_root(request: PostcheckRequest, response: Response) -> PostcheckApiResponse:
        """Validate a model response before returning it to the caller."""

        status_code, postcheck_response = postcheck_request(request)
        response.status_code = status_code
        return postcheck_response

    return app


app = create_app()
