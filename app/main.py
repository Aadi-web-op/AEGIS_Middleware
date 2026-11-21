import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.audit import AuditLogger, decisions_router
from app.auth import (
    AuthMiddleware,
    LoginLimiter,
    SecurityHeadersMiddleware,
    UserStore,
    api_keys_from_env,
    auth_enabled_from_env,
    auth_router,
    ensure_admin,
)
from app.core.config import UnknownProfileError
from app.core.evaluator import Evaluator
from app.core.explainer import explain_escalation
from app.escalation import EscalationQueue, escalation_router
from app.evidence.highlight import build_highlights
from app.evidence.registry import default_signals
from app.graph.insights import (
    conflicting_document_pairs,
    escalations_by_root_cause,
    frequent_abstain_topics,
    impacted_decisions_for_document,
    outdated_documents_retrieved,
)
from app.graph.async_sink import AsyncGraphSink
from app.graph.driver import make_driver
from app.graph.events import GraphEvents, router as graph_events_router
from app.graph.neo4j_sink import Neo4jGraphSink
from app.graph.routes import router as graph_router
from app.graph.sink import GraphSink
from app.insights import insights_router
from app.intelligence import intelligence_router
from app.rag.routes import router as rag_router
from app.schemas import Decision, EvaluateRequest, EvaluateResponse, RecommendedAction

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def _allowed_origins() -> list[str]:
    raw = os.environ.get("AEGIS_CORS_ORIGINS", DEFAULT_ORIGINS)
    # Browsers send Origin without a trailing slash; tolerate "https://x.app/" in config.
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def _init_neo4j_driver() -> Any | None:
    uri = os.environ.get("NEO4J_URI")
    if not uri:
        return None
    try:
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")
        # Short timeouts: a dead Neo4j must be noticed in seconds.
        return make_driver(uri, user, password)
    except Exception:
        logger.warning("Could not initialize Neo4j driver for %s", uri)
        return None


def create_app(
    evaluator: Evaluator | None = None,
    neo4j_driver: Any | None = None,
    graph_sink: GraphSink | None = None,
    audit_logger: AuditLogger | None = None,
    escalation_queue: EscalationQueue | None = None,
    user_store: UserStore | None = None,
    auth_enabled: bool | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Lifespan, not add_event_handler/on_event: Starlette 1.x removed those.
        yield
        writer = getattr(app.state.evaluator, "graph_sink", None)
        if isinstance(writer, AsyncGraphSink):
            writer.close(timeout=5.0)

    app = FastAPI(
        title="Aegis",
        version=API_VERSION,
        description="Uncertainty middleware: decides whether an AI answer should be "
        "returned, caveated, escalated or withheld.",
        lifespan=lifespan,
        # Interactive docs are handy locally; set AEGIS_DOCS_ENABLED=0 in production.
        **({} if os.environ.get("AEGIS_DOCS_ENABLED", "1") != "0"
           else {"docs_url": None, "redoc_url": None, "openapi_url": None}),
    )

    driver = neo4j_driver if neo4j_driver is not None else _init_neo4j_driver()
    app.state.neo4j_driver = driver
    app.state.rag_ingestion_lock = Lock()
    app.state.graph_events = GraphEvents()

    if evaluator is None:
        sink = graph_sink
        if sink is None and driver is not None:
            # Background writer: Neo4j is never on the decision path.
            sink = AsyncGraphSink(Neo4jGraphSink(driver))
        evaluator = Evaluator(default_signals(), graph_sink=sink)
    elif graph_sink is not None:
        evaluator.graph_sink = graph_sink
    elif driver is not None and getattr(evaluator, "graph_sink", None) is None:
        evaluator.graph_sink = AsyncGraphSink(Neo4jGraphSink(driver))

    app.state.evaluator = evaluator

    def finish_evaluation(
        payload: EvaluateRequest, response: EvaluateResponse
    ) -> EvaluateResponse:
        try:
            response.counterfactual = explain_escalation(payload, response, app.state.evaluator.config)
        except Exception:
            logger.exception("Could not explain decision %s", response.request_id)
        try:
            response.highlights = build_highlights(payload, response)
        except Exception:
            logger.exception("Could not highlight evidence for %s", response.request_id)
        if response.trace is not None:
            try:
                app.state.graph_events.publish(response.trace)
            except Exception:
                logger.exception("Could not publish decision trace %s", response.request_id)
        return response

    app.state.finish_evaluation = finish_evaluation
    app.state.audit_logger = audit_logger if audit_logger is not None else AuditLogger()
    app.state.escalation_queue = (
        escalation_queue if escalation_queue is not None else EscalationQueue()
    )

    app.include_router(rag_router)
    app.include_router(graph_events_router)
    app.include_router(escalation_router)
    app.include_router(insights_router)
    app.include_router(graph_router)
    app.include_router(decisions_router)
    app.include_router(intelligence_router)
    app.include_router(auth_router)

    # Middleware runs outermost-last-added: CORS -> security headers -> auth -> routes.
    origins = _allowed_origins()
    if auth_enabled is None:
        auth_enabled = auth_enabled_from_env()
    app.state.user_store = None
    app.state.login_limiter = LoginLimiter()
    if auth_enabled:
        store = user_store if user_store is not None else UserStore()
        ensure_admin(store)
        app.state.user_store = store
        app.add_middleware(AuthMiddleware, store=store, api_keys=api_keys_from_env(),
                           allowed_origins=origins)
    app.add_middleware(SecurityHeadersMiddleware,
                       force_hsts=os.environ.get("AEGIS_HSTS") == "1")
    if "*" in origins:
        logger.warning("AEGIS_CORS_ORIGINS contains '*': credentials are not allowed cross-origin.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
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
        response = app.state.evaluator.evaluate(payload)

        audit_log = getattr(app.state, "audit_logger", None)
        if audit_log is not None:
            try:
                audit_log.log_evaluation(payload, response)
            except Exception as exc:
                logger.warning("Failed to log evaluation: %s", exc)

        escalation_q = getattr(app.state, "escalation_queue", None)
        if escalation_q is not None and (
            response.decision == Decision.ESCALATE
            or response.recommended_action == RecommendedAction.ESCALATE_TO_HUMAN
        ):
            reason_msg = (
                "; ".join(r.message for r in response.reasons)
                if response.reasons
                else "Evaluator escalated case to human review."
            )
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

        return finish_evaluation(payload, response)

    # ---------------------------------------------------------------------------
    # /v1/insights/* endpoints exposing Shatakshi's cross-decision Neo4j queries
    # ---------------------------------------------------------------------------

    @app.get("/v1/insights/conflicts")
    def get_conflicting_document_pairs(limit: int = Query(default=10, ge=1, le=100)):
        drv = app.state.neo4j_driver
        if drv is None:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Neo4j is not connected. Decision Graph insights are unavailable."
                },
            )
        try:
            return conflicting_document_pairs(drv, limit=limit)
        except Exception as exc:
            logger.exception("Failed to execute conflicting_document_pairs")
            return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/v1/insights/outdated")
    def get_outdated_documents(limit: int = Query(default=10, ge=1, le=100)):
        drv = app.state.neo4j_driver
        if drv is None:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Neo4j is not connected. Decision Graph insights are unavailable."
                },
            )
        try:
            return outdated_documents_retrieved(drv, limit=limit)
        except Exception as exc:
            logger.exception("Failed to execute outdated_documents_retrieved")
            return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/v1/insights/abstains")
    def get_frequent_abstain_topics(limit: int = Query(default=10, ge=1, le=100)):
        drv = app.state.neo4j_driver
        if drv is None:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Neo4j is not connected. Decision Graph insights are unavailable."
                },
            )
        try:
            return frequent_abstain_topics(drv, limit=limit)
        except Exception as exc:
            logger.exception("Failed to execute frequent_abstain_topics")
            return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/v1/insights/impact")
    def get_impacted_decisions_for_document(
        source: str = Query(..., min_length=1),
        version: str | None = Query(default=None),
    ):
        drv = app.state.neo4j_driver
        if drv is None:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Neo4j is not connected. Decision Graph insights are unavailable."
                },
            )
        try:
            return impacted_decisions_for_document(drv, source=source, version=version)
        except Exception as exc:
            logger.exception("Failed to execute impacted_decisions_for_document")
            return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/v1/insights/escalations")
    def get_escalations_by_root_cause(limit: int = Query(default=10, ge=1, le=100)):
        drv = app.state.neo4j_driver
        if drv is None:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Neo4j is not connected. Decision Graph insights are unavailable."
                },
            )
        try:
            return escalations_by_root_cause(drv, limit=limit)
        except Exception as exc:
            logger.exception("Failed to execute escalations_by_root_cause")
            return JSONResponse(status_code=500, content={"detail": str(exc)})

    return app


app = create_app()
