"""/v1/decisions -- decision history from the SQLite audit log.

SQLite is the system of record, so decision history works whether or not
Neo4j is running. The full response (including its decision trace) is
available for evaluations logged after `response_json` was introduced;
older rows return `response: null`.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import Decision

router = APIRouter(prefix="/v1/decisions", tags=["Decisions"])

_SUMMARY_FIELDS = (
    "request_id",
    "timestamp",
    "query",
    "profile",
    "decision",
    "answerability_score",
    "reason_codes",
    "generation_success",
    "error_message",
    "latency_ms",
)


def _audit(request: Request):
    audit = getattr(request.app.state, "audit_logger", None)
    if audit is None:
        raise HTTPException(status_code=503, detail="Audit log is not configured.")
    return audit


@router.get("")
def list_decisions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    decision: Optional[Decision] = Query(default=None),
):
    audit = _audit(request)
    rows = audit.list_records(
        limit=limit,
        offset=offset,
        decision=decision.value if decision else None,
    )
    raw_counts = audit.count_records()
    # `counts` holds only the four AEGIS decisions. Rows with no decision are
    # failed answer generations (the LLM never produced an answer, so AEGIS
    # never decided); they are reported separately, not as a fifth outcome.
    counts = {d.value: raw_counts.get(d.value, 0) for d in Decision if raw_counts.get(d.value)}
    generation_failures = sum(v for k, v in raw_counts.items() if k not in {d.value for d in Decision})
    return {
        "items": [{k: row.get(k) for k in _SUMMARY_FIELDS} for row in rows],
        # All logged requests, including generation failures (what paging walks).
        "total": sum(raw_counts.values()),
        "counts": counts,
        "generation_failures": generation_failures,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{request_id}")
def get_decision(request_id: str, request: Request):
    record = _audit(request).get_record(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No decision {request_id!r} in the audit log.")
    response = record.pop("response", None)
    return {"record": record, "response": response}
