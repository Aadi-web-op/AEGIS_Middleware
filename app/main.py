import os
from app.rag.routes import router as rag_router

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import UnknownProfileError
from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.schemas import EvaluateRequest, EvaluateResponse

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
    app.include_router(rag_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(UnknownProfileError)
    async def unknown_profile_handler(request: Request, exc: UnknownProfileError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

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
