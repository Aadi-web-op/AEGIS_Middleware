"""
/v1/insights/* endpoints — cross-decision analytics derived from the SQLite audit log.

Actual audit_logs table schema (from app/audit/logger.py):
    request_id, timestamp, query, answer, profile, decision,
    answerability_score, signals (JSON), reason_codes (JSON list of code strings),
    generation_success, error_message, latency_ms

NOTE: evidence is NOT persisted in the audit log, so source-pair analytics are
approximated from the signal data (contradiction score) and the query text.
"""
from __future__ import annotations

import json
import logging
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request

from app.audit import default_audit_db_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/insights", tags=["Insights"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audit_db_path(request: Request) -> str:
    override = getattr(request.app.state, "audit_db_path", None)
    if override:
        return str(override)
    return str(default_audit_db_path())


def _safe_query(db_path: str, sql: str, params: tuple = ()) -> list[dict]:
    """Execute a read-only query against the audit DB; raise 503 if unavailable."""
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Audit database unavailable: {exc}",
        ) from exc


def _safe_query_plain(db_path: str, sql: str, params: tuple = ()) -> list[dict]:
    """Same as _safe_query but used for escalations.db (regular path, not uri=ro)."""
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Escalation database unavailable: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# 1. Requests with high contradiction signal — a proxy for conflicting evidence
# ---------------------------------------------------------------------------

@router.get("/conflicting-document-pairs")
def conflicting_document_pairs(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
):
    """
    Return requests where the contradiction signal exceeded 0.5, ordered by
    contradiction severity.  Source-pair information is not persisted in the
    audit log; the endpoint returns query-level records so the UI can show
    which questions triggered conflicts.
    """
    db_path = _audit_db_path(request)
    rows = _safe_query(
        db_path,
        """
        SELECT request_id, query, decision, answerability_score, signals, timestamp
        FROM audit_logs
        WHERE decision IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT 1000
        """,
    )

    results = []
    for row in rows:
        try:
            sigs = json.loads(row.get("signals") or "{}")
        except (ValueError, TypeError):
            sigs = {}
        contradiction = sigs.get("contradiction")
        if contradiction is not None and contradiction >= 0.5:
            results.append({
                "request_id": row.get("request_id"),
                "query": row.get("query") or "",
                "contradiction_score": round(contradiction, 3),
                "decision": row.get("decision") or "",
                "answerability_score": row.get("answerability_score"),
                "timestamp": row.get("timestamp") or "",
            })
    results.sort(key=lambda x: x["contradiction_score"], reverse=True)
    return results[:limit]


# ---------------------------------------------------------------------------
# 2. Requests where freshness was low (evidence may be stale)
# ---------------------------------------------------------------------------

@router.get("/stale-document-retrievals")
def stale_document_retrievals(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
):
    """
    Return requests where freshness < 0.5, ordered by freshness ascending
    (worst first).  Since evidence sources are not persisted, we return
    query-level records with signal data.
    """
    db_path = _audit_db_path(request)
    rows = _safe_query(
        db_path,
        """
        SELECT request_id, query, decision, signals, timestamp
        FROM audit_logs
        WHERE decision IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT 1000
        """,
    )

    results = []
    for row in rows:
        try:
            sigs = json.loads(row.get("signals") or "{}")
        except (ValueError, TypeError):
            sigs = {}
        freshness = sigs.get("freshness")
        if freshness is not None and freshness < 0.5:
            results.append({
                "request_id": row.get("request_id"),
                "query": row.get("query") or "",
                "freshness_score": round(freshness, 3),
                "decision": row.get("decision") or "",
                "timestamp": row.get("timestamp") or "",
            })
    results.sort(key=lambda x: x["freshness_score"])
    return results[:limit]


# ---------------------------------------------------------------------------
# 3. Topics that most frequently led to ABSTAIN
# ---------------------------------------------------------------------------

@router.get("/abstain-topics")
def abstain_topics(
    request: Request,
    limit: int = Query(15, ge=1, le=100),
):
    """Return ABSTAIN decisions with their reason codes and queries."""
    db_path = _audit_db_path(request)
    rows = _safe_query(
        db_path,
        """
        SELECT request_id, query, reason_codes, timestamp
        FROM audit_logs
        WHERE decision = 'ABSTAIN'
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (limit,),
    )
    results = []
    for row in rows:
        try:
            codes = json.loads(row.get("reason_codes") or "[]")
        except (ValueError, TypeError):
            codes = []
        results.append({
            "request_id": row.get("request_id"),
            "query": row.get("query") or "",
            "reason_codes": codes,
            "timestamp": row.get("timestamp") or "",
        })
    return results


# ---------------------------------------------------------------------------
# 4. Past decisions (looked up by decision value for a broad history view)
# ---------------------------------------------------------------------------

@router.get("/decisions-by-decision")
def decisions_by_decision(
    request: Request,
    decision: str = Query("ESCALATE", description="Decision value: ANSWER, CAVEAT, ESCALATE, ABSTAIN"),
    limit: int = Query(20, ge=1, le=200),
):
    """
    Return audit records matching a given decision value.
    Use this to find all past escalations, abstentions, etc.
    """
    db_path = _audit_db_path(request)
    rows = _safe_query(
        db_path,
        """
        SELECT request_id, query, decision, answerability_score, signals, reason_codes, timestamp
        FROM audit_logs
        WHERE decision = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (decision.upper(), limit),
    )
    results = []
    for row in rows:
        try:
            sigs = json.loads(row.get("signals") or "{}")
        except (ValueError, TypeError):
            sigs = {}
        try:
            codes = json.loads(row.get("reason_codes") or "[]")
        except (ValueError, TypeError):
            codes = []
        results.append({
            "request_id": row.get("request_id"),
            "query": row.get("query") or "",
            "decision": row.get("decision") or "",
            "answerability_score": row.get("answerability_score"),
            "signals": sigs,
            "reason_codes": codes,
            "timestamp": row.get("timestamp") or "",
        })
    return results


# ---------------------------------------------------------------------------
# 5. Escalations grouped by reason code (root-cause cluster)
# ---------------------------------------------------------------------------

@router.get("/escalation-clusters")
def escalation_clusters(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
):
    """
    Return pending/in-review escalations joined with audit reason_codes,
    grouped by the dominant reason code.
    """
    from app.escalation.queue import default_escalations_db_path
    esc_db = str(default_escalations_db_path())

    try:
        esc_rows = _safe_query_plain(
            esc_db,
            """
            SELECT escalation_id, request_id, reason, decision, status, created_at
            FROM escalations
            WHERE status IN ('pending', 'in_review')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
    except HTTPException:
        esc_rows = []

    # Optionally enrich with reason_codes from audit log
    db_path = _audit_db_path(request)
    audit_by_rid: dict[str, list[str]] = {}
    if esc_rows:
        rids = tuple(r["request_id"] for r in esc_rows)
        placeholders = ",".join("?" * len(rids))
        try:
            audit_data = _safe_query(
                db_path,
                f"SELECT request_id, reason_codes FROM audit_logs WHERE request_id IN ({placeholders})",
                rids,
            )
            for a in audit_data:
                try:
                    codes = json.loads(a.get("reason_codes") or "[]")
                except (ValueError, TypeError):
                    codes = []
                audit_by_rid[a["request_id"]] = codes
        except HTTPException:
            pass

    clusters: dict[str, dict] = {}
    for row in esc_rows:
        rid = row.get("request_id", "")
        codes = audit_by_rid.get(rid, [])
        code = codes[0] if codes else "UNKNOWN"
        if code not in clusters:
            clusters[code] = {
                "reason_code": code,
                "count": 0,
                "escalation_ids": [],
                "request_ids": [],
            }
        clusters[code]["count"] += 1
        clusters[code]["escalation_ids"].append(row.get("escalation_id"))
        clusters[code]["request_ids"].append(rid)

    return sorted(clusters.values(), key=lambda x: x["count"], reverse=True)
