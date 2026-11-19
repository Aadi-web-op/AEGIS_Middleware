"""`/v1/graph/*`: read-only access to the stored decision graph.

Neo4j is optional. With no driver configured, or with the server
unreachable, every endpoint except `/status` answers
`503 {"detail": ..., "graph_available": false}`; `/status` always
answers 200 and reports `connected: false`.

An unreachable server costs a caller a few seconds (the driver's
connection timeout). To keep a polling UI from paying that on every
request, a failure is remembered for `DOWN_TTL_SECONDS` and requests in
that window fail fast.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.graph.contract import DECISIONS
from app.graph.reader import MAX_LIMIT, GraphReader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/graph", tags=["graph"])

DOWN_TTL_SECONDS = 10.0

_NOT_CONFIGURED = "Neo4j is not configured. The decision graph is unavailable."
_UNREACHABLE = "Neo4j is not reachable. The decision graph is unavailable."

_EMPTY_WRITER: Dict[str, Any] = {
    "written": 0,
    "failed": 0,
    "dropped": 0,
    "pending": 0,
    "last_error": None,
    "last_success_at": None,
}


def _unavailable(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"detail": detail, "graph_available": False}
    )


def _not_found(detail: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": detail})


def _driver(request: Request) -> Any:
    return getattr(request.app.state, "neo4j_driver", None)


def _recently_down(request: Request) -> bool:
    until = getattr(request.app.state, "graph_down_until", 0.0)
    return time.monotonic() < until


def _mark_down(request: Request) -> None:
    request.app.state.graph_down_until = time.monotonic() + DOWN_TTL_SECONDS


def _mark_up(request: Request) -> None:
    request.app.state.graph_down_until = 0.0


def _writer_stats(request: Request) -> Dict[str, Any]:
    """Counters of the background graph writer, if one is wired in."""
    evaluator = getattr(request.app.state, "evaluator", None)
    sink = getattr(evaluator, "graph_sink", None)
    stats = getattr(sink, "stats", None)
    if callable(stats):
        try:
            return {**_EMPTY_WRITER, **dict(stats())}
        except Exception:
            logger.exception("Could not read graph writer stats")
    return dict(_EMPTY_WRITER)


def _run(request: Request, call: Any) -> Any:
    """Run a reader call; returns (result, None) or (None, 503 response)."""
    driver = _driver(request)
    if driver is None:
        return None, _unavailable(_NOT_CONFIGURED)
    if _recently_down(request):
        return None, _unavailable(_UNREACHABLE)
    try:
        result = call(GraphReader(driver))
    except Exception:
        # Deliberately broad: connection, auth and timeout errors all mean
        # "the graph cannot answer right now". Details go to the log, not
        # to the client.
        logger.exception("Graph read failed for %s", request.url.path)
        _mark_down(request)
        return None, _unavailable(_UNREACHABLE)
    _mark_up(request)
    return result, None


@router.get("/status")
def graph_status(request: Request) -> Dict[str, Any]:
    """Whether the graph is configured and reachable, with counts."""
    driver = _driver(request)
    payload: Dict[str, Any] = {
        "configured": driver is not None,
        "connected": False,
        "counts": {},
        "relationships": {},
        "writer": _writer_stats(request),
    }
    if driver is None or _recently_down(request):
        return payload
    try:
        counts = GraphReader(driver).counts()
    except Exception:
        logger.warning("Graph status check failed; reporting connected=false", exc_info=True)
        _mark_down(request)
        return payload
    _mark_up(request)
    payload.update(connected=True, **counts)
    return payload


@router.get("/decisions")
def graph_decisions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    decision: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None, max_length=512),
):
    """Stored decisions, newest first. Filter by outcome and/or source."""
    decision = (decision or "").strip().upper() or None
    if decision is not None and decision not in DECISIONS:
        return JSONResponse(
            status_code=422,
            content={"detail": f"decision must be one of {list(DECISIONS)}"},
        )
    source = (source or "").strip() or None
    items, error = _run(
        request,
        lambda reader: reader.list_decisions(limit=limit, decision=decision, source=source),
    )
    if error is not None:
        return error
    return {"items": items}


@router.get("/decisions/{request_id}")
def graph_decision(request: Request, request_id: str):
    """One decision's subgraph: claims, evidence, documents, reasons."""
    subgraph, error = _run(request, lambda reader: reader.decision_subgraph(request_id))
    if error is not None:
        return error
    if subgraph is None:
        return _not_found(f"No decision {request_id!r} in the graph.")
    return subgraph


@router.get("/documents")
def graph_documents(
    request: Request,
    limit: int = Query(default=100, ge=1, le=MAX_LIMIT),
):
    """Documents with usage, support, conflict and supersession counts."""
    items, error = _run(request, lambda reader: reader.list_documents(limit=limit))
    if error is not None:
        return error
    return {"items": items}


@router.get("/nodes/{node_id:path}/neighbors")
def graph_neighbors(
    request: Request,
    node_id: str,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
):
    """One-hop subgraph around any node (used to expand the explorer)."""
    subgraph, error = _run(request, lambda reader: reader.neighbors(node_id, limit=limit))
    if error is not None:
        return error
    if subgraph is None:
        return _not_found(f"No node {node_id!r} in the graph.")
    return subgraph
