import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import UnknownProfileError
from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.graph.insights import (
    conflicting_document_pairs,
    escalations_by_root_cause,
    frequent_abstain_topics,
    impacted_decisions_for_document,
    outdated_documents_retrieved,
)
from app.graph.neo4j_sink import Neo4jGraphSink
from app.graph.sink import GraphSink
from app.schemas import EvaluateRequest, EvaluateResponse

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def _allowed_origins() -> list[str]:
    raw = os.environ.get("AEGIS_CORS_ORIGINS", DEFAULT_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _init_neo4j_driver() -> Any | None:
    uri = os.environ.get("NEO4J_URI")
    if not uri:
        return None
    try:
        from neo4j import GraphDatabase

        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")
        return GraphDatabase.driver(uri, auth=(user, password))
    except Exception:
        logger.warning("Could not initialize Neo4j driver for %s", uri)
        return None


def create_app(
    evaluator: Evaluator | None = None,
    neo4j_driver: Any | None = None,
    graph_sink: GraphSink | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Aegis",
        version=API_VERSION,
        description="Uncertainty middleware: decides whether an AI answer should be "
        "returned, caveated, escalated or withheld.",
    )

    driver = neo4j_driver if neo4j_driver is not None else _init_neo4j_driver()
    app.state.neo4j_driver = driver

    if evaluator is None:
        sink = graph_sink
        if sink is None and driver is not None:
            sink = Neo4jGraphSink(driver)
        evaluator = Evaluator(default_signals(), graph_sink=sink)
    elif graph_sink is not None:
        evaluator.graph_sink = graph_sink
    elif driver is not None and getattr(evaluator, "graph_sink", None) is None:
        evaluator.graph_sink = Neo4jGraphSink(driver)

    app.state.evaluator = evaluator

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
