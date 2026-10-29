import os
import logging


from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import UnknownProfileError
from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.schemas import EvaluateRequest, EvaluateResponse

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def _allowed_origins() -> list[str]:
    raw = os.environ.get("AEGIS_CORS_ORIGINS", DEFAULT_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app(evaluator: Evaluator | None = None) -> FastAPI:
    app = FastAPI(
        title="Aegis",
        version=API_VERSION,
        description="Uncertainty middleware: decides whether an AI answer should be "
                    "returned, caveated, escalated or withheld.",
    )
    app.state.evaluator = evaluator if evaluator is not None else Evaluator(default_signals())

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(UnknownProfileError)
    async def unknown_profile_handler(request: Request, exc: UnknownProfileError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def fail_closed_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error while serving %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Aegis could not evaluate this request. Treat the answer as ABSTAIN.",
                "fail_closed": True,
            },
        )
        
    @app.get("/v1/health")
    def health():
        ev = app.state.evaluator
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "policy_version": ev.config.version,
            "signals": [s.name for s in ev.signals],
        }

    @app.get("/v1/config")
    def get_config():
        return app.state.evaluator.config.model_dump()

    @app.post("/v1/evaluate", response_model=EvaluateResponse)
    def evaluate(payload: EvaluateRequest):
        return app.state.evaluator.evaluate(payload)

    return app


app = create_app()
