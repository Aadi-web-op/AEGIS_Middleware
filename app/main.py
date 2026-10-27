import logging
import os
from app.insights import insights_router
from app.rag.routes import router as rag_router

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.audit import AuditLogger
from app.core.config import UnknownProfileError
from app.core.evaluator import Evaluator
from app.escalation import EscalationQueue, escalation_router
from app.evidence.registry import default_signals
from app.schemas import Decision, EvaluateRequest, EvaluateResponse, RecommendedAction

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def _allowed_origins() -> list[str]:
    raw = os.environ.get("AEGIS_CORS_ORIGINS", DEFAULT_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app(
    evaluator: Evaluator | None = None,
    audit_logger: AuditLogger | None = None,
    escalation_queue: EscalationQueue | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Aegis",
        version=API_VERSION,
        description="Uncertainty middleware: decides whether an AI answer should be "
                    "returned, caveated, escalated or withheld.",
    )
    app.state.evaluator = evaluator if evaluator is not None else Evaluator(default_signals())
    app.state.audit_logger = audit_logger if audit_logger is not None else AuditLogger()
    app.state.escalation_queue = escalation_queue if escalation_queue is not None else EscalationQueue()
    app.include_router(rag_router)
    app.include_router(escalation_router)
    app.include_router(insights_router)

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
        response = app.state.evaluator.evaluate(payload)
        audit_log = getattr(app.state, "audit_logger", None)
        if audit_log is not None:
            audit_log.log_evaluation(payload, response)

        escalation_q = getattr(app.state, "escalation_queue", None)
        if escalation_q is not None and (
            response.decision == Decision.ESCALATE
            or response.recommended_action == RecommendedAction.ESCALATE_TO_HUMAN
        ):
            reason_msg = "; ".join(r.message for r in response.reasons) if response.reasons else "Evaluator escalated case to human review."
            try:
                escalation_q.enqueue(
                    request_id=response.request_id,
                    reason=reason_msg,
                    decision=response.decision.value,
                    query=payload.query,
                    answer=payload.answer,
                    notes=f"Auto-escalated by policy. Action: {response.recommended_action.value}",
                    raise_on_duplicate=False,
                )
            except Exception as exc:
                logger.warning("Failed to auto-enqueue escalation: %s", exc)
        return response

    return app


app = create_app()
