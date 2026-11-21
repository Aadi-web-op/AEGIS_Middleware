"""/v1/intelligence -- cross-decision reliability intelligence.

`/summary` and `/trends` answer from the audit log even when Neo4j is
down (`/summary` then reports `graph.available: false`). The other
endpoints are graph-only and return 503 `{"detail", "graph_available":
false}` when the graph cannot be read.

An unreachable Neo4j costs a request a few seconds. As in `/v1/graph`, a
connectivity failure is remembered for `DOWN_TTL_SECONDS` (the same
`app.state.graph_down_until` marker), so a polling UI fails fast.

`request_prefix` scopes every endpoint to decisions whose request_id
starts with it; the default (omitted) is all stored decisions.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.intelligence.audit import AuditReader, AuditUnavailable
from app.intelligence.service import GraphUnavailable, IntelligenceService

router = APIRouter(prefix="/v1/intelligence", tags=["Intelligence"])

#: Seconds a connectivity failure is remembered (matches app.graph.routes).
DOWN_TTL_SECONDS = 10.0

_PREFIX = Query(default=None, max_length=128, description="Only decisions whose request_id starts with this.")


def _service(request: Request) -> IntelligenceService:
    state = request.app.state
    audit = AuditReader(
        audit_logger=getattr(state, "audit_logger", None),
        db_path=getattr(state, "audit_db_path", None),
    )
    down = time.monotonic() < getattr(state, "graph_down_until", 0.0)
    return IntelligenceService(
        driver=getattr(state, "neo4j_driver", None), audit=audit, graph_known_down=down
    )


def _remember(request: Request, svc: IntelligenceService, ok: bool) -> None:
    if svc.graph_known_down:
        return
    if svc.unreachable:
        request.app.state.graph_down_until = time.monotonic() + DOWN_TTL_SECONDS
    elif ok and svc.driver is not None:
        request.app.state.graph_down_until = 0.0


def _graph_only(request: Request, fn: Callable[[IntelligenceService], object]):
    svc = _service(request)
    try:
        result = fn(svc)
    except GraphUnavailable as exc:
        _remember(request, svc, ok=False)
        return JSONResponse(
            status_code=503, content={"detail": str(exc), "graph_available": False}
        )
    _remember(request, svc, ok=True)
    return result


@router.get("/summary")
def summary(request: Request, request_prefix: Optional[str] = _PREFIX):
    svc = _service(request)
    result = svc.summary(request_prefix or "")
    _remember(request, svc, ok=bool(result["graph"].get("available")))
    return result


@router.get("/documents")
def documents(request: Request, request_prefix: Optional[str] = _PREFIX):
    return _graph_only(request, lambda svc: svc.documents(request_prefix or ""))


@router.get("/contradictions")
def contradictions(request: Request, request_prefix: Optional[str] = _PREFIX):
    return _graph_only(request, lambda svc: svc.contradictions(request_prefix or ""))


@router.get("/stale-usage")
def stale_usage(request: Request, request_prefix: Optional[str] = _PREFIX):
    return _graph_only(request, lambda svc: svc.stale_usage(request_prefix or ""))


@router.get("/knowledge-gaps")
def knowledge_gaps(request: Request, request_prefix: Optional[str] = _PREFIX):
    return _graph_only(request, lambda svc: svc.knowledge_gaps(request_prefix or ""))


@router.get("/blast-radius")
def blast_radius(
    request: Request,
    doc_id: str = Query(..., min_length=1, description="Document id, e.g. doc:leave_policy.pdf@v1"),
    request_prefix: Optional[str] = _PREFIX,
):
    def run(svc: IntelligenceService):
        result = svc.blast_radius(doc_id, request_prefix or "")
        if result is None:
            return JSONResponse(
                status_code=404,
                content={"detail": f"No Document with id {doc_id!r} in the decision graph."},
            )
        return result

    return _graph_only(request, run)


@router.get("/trends")
def trends(
    request: Request,
    bucket: str = Query(default="day", pattern="^(day|hour)$"),
    request_prefix: Optional[str] = _PREFIX,
):
    try:
        return _service(request).trends(bucket, request_prefix or "")
    except AuditUnavailable as exc:
        return JSONResponse(
            status_code=503, content={"detail": f"Audit database unavailable: {exc}"}
        )
