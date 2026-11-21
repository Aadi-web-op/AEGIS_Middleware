"""
/v1/insights/* endpoints — cross-decision analytics for Aegis.

Supports two data engines:
1. Decision Graph (Neo4j): Real cross-decision graph traversal using Cypher queries
   (conflicting document pairs, outdated documents retrieved, knowledge gaps ending in ABSTAIN,
   impacted decisions blast radius, and escalations by root-cause document).
2. SQLite Audit Log & Escalation Queue: Robust offline fallback when Neo4j is offline.

Matches the specification in "AEGIS Finale Plan: Decisions & Task Split" (Nov 17, 2026):
- Cross-decision Cypher queries, their endpoints, and the Insights panel
- Calibration and empirical band
- Auditor export
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app.audit import default_audit_db_path
from app.escalation.queue import default_escalations_db_path
from app.graph.insights import (
    conflicting_document_pairs as neo4j_conflicting_pairs,
    escalations_by_root_cause as neo4j_escalations_by_root_cause,
    frequent_abstain_topics as neo4j_frequent_abstain_topics,
    impacted_decisions_for_document as neo4j_impacted_decisions,
    outdated_documents_retrieved as neo4j_outdated_documents,
)

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


def _escalations_db_path(request: Request) -> str:
    override = getattr(request.app.state, "escalations_db_path", None)
    if override:
        return str(override)
    esc_q = getattr(request.app.state, "escalation_queue", None)
    if esc_q and hasattr(esc_q, "db_path"):
        return str(esc_q.db_path)
    return str(default_escalations_db_path())


def _get_neo4j_driver(request: Request) -> Any | None:
    return getattr(request.app.state, "neo4j_driver", None)


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
    """Same as _safe_query but used for escalations.db."""
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
# 1. Conflicting Document Pairs
# ---------------------------------------------------------------------------

@router.get("/conflicting-document-pairs")
@router.get("/conflicts")
def conflicting_document_pairs(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
):
    """
    Return document pairs that disagree with each other.
    Uses Neo4j cross-decision graph traversal when available; falls back to audit log.
    """
    drv = _get_neo4j_driver(request)
    if drv is not None:
        try:
            raw = neo4j_conflicting_pairs(drv, limit=limit)
            if raw:
                return [
                    {
                        "request_id": f"conflict-{r.get('doc_a')}-{r.get('doc_b')}",
                        "query": f"Document conflict: {r.get('source_a')} vs {r.get('source_b')}",
                        "source_a": r.get("source_a"),
                        "version_a": r.get("version_a"),
                        "doc_a": r.get("doc_a"),
                        "source_b": r.get("source_b"),
                        "version_b": r.get("version_b"),
                        "doc_b": r.get("doc_b"),
                        "conflict_kinds": r.get("conflict_kinds", []),
                        "conflict_count": r.get("conflict_count", 0),
                        "contradiction_score": 0.85,
                        "decision": "ESCALATE",
                        "answerability_score": 0.35,
                        "timestamp": "",
                    }
                    for r in raw
                ]
        except Exception as exc:
            logger.warning("Neo4j conflicting_document_pairs failed, falling back: %s", exc)

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
# 2. Outdated / Stale Document Retrievals
# ---------------------------------------------------------------------------

@router.get("/stale-document-retrievals")
@router.get("/outdated")
def stale_document_retrievals(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
):
    """
    Return decisions answered from outdated documents while newer versions exist.
    Uses Neo4j SUPERSEDES relationship when available; falls back to freshness signal.
    """
    drv = _get_neo4j_driver(request)
    if drv is not None:
        try:
            raw = neo4j_outdated_documents(drv, limit=limit)
            if raw:
                return [
                    {
                        "request_id": f"outdated-{r.get('source')}-{r.get('outdated_version')}",
                        "query": f"{r.get('source')} (v{r.get('outdated_version')} superseded by v{r.get('newer_version')})",
                        "source": r.get("source"),
                        "outdated_version": r.get("outdated_version"),
                        "outdated_doc_id": r.get("outdated_doc_id"),
                        "newer_version": r.get("newer_version"),
                        "newer_doc_id": r.get("newer_doc_id"),
                        "retrieved_chunk_count": r.get("retrieved_chunk_count", 0),
                        "affected_decisions_count": r.get("affected_decisions_count", 0),
                        "freshness_score": 0.25,
                        "decision": "ESCALATE",
                        "timestamp": "",
                    }
                    for r in raw
                ]
        except Exception as exc:
            logger.warning("Neo4j outdated_documents failed, falling back: %s", exc)

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
# 3. Topics Leading to ABSTAIN (Knowledge Gaps)
# ---------------------------------------------------------------------------

@router.get("/abstain-topics")
@router.get("/abstains")
def abstain_topics(
    request: Request,
    limit: int = Query(15, ge=1, le=100),
):
    """
    Return questions the corpus could not answer (knowledge-base gaps).
    """
    drv = _get_neo4j_driver(request)
    if drv is not None:
        try:
            raw = neo4j_frequent_abstain_topics(drv, limit=limit)
            if raw:
                formatted = []
                for idx, r in enumerate(raw):
                    sample_q = (
                        (r.get("sample_claims") or ["Knowledge base gap"])[0]
                        if r.get("sample_claims")
                        else r.get("sample_reason", "Documentation gap")
                    )
                    formatted.append({
                        "request_id": (r.get("sample_request_ids") or [f"gap-{idx}"])[0],
                        "query": sample_q,
                        "reason_codes": [r.get("reason_code", "NO_EVIDENCE")],
                        "abstain_count": r.get("abstain_count", 1),
                        "timestamp": "",
                    })
                return formatted
        except Exception as exc:
            logger.warning("Neo4j frequent_abstain_topics failed, falling back: %s", exc)

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
# 4. Past Decisions by Status
# ---------------------------------------------------------------------------

@router.get("/decisions-by-decision")
def decisions_by_decision(
    request: Request,
    decision: str = Query("ESCALATE", description="Decision value: ANSWER, CAVEAT, ESCALATE, ABSTAIN"),
    limit: int = Query(20, ge=1, le=200),
):
    """
    Return audit records matching a given decision value.
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
# 5. Escalation Clusters by Root Cause
# ---------------------------------------------------------------------------

@router.get("/escalation-clusters")
@router.get("/root-causes")
def escalation_clusters(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
):
    """
    Group escalations by shared root cause document/reason.
    """
    drv = _get_neo4j_driver(request)
    if drv is not None:
        try:
            raw = neo4j_escalations_by_root_cause(drv, limit=limit)
            if raw:
                return [
                    {
                        "reason_code": r.get("root_cause_code", "UNKNOWN"),
                        "source": r.get("source"),
                        "version": r.get("version"),
                        "count": r.get("escalation_count", 0),
                        "request_ids": r.get("escalation_request_ids", []),
                        "sample_messages": r.get("sample_messages", []),
                    }
                    for r in raw
                ]
        except Exception as exc:
            logger.warning("Neo4j escalations_by_root_cause failed, falling back: %s", exc)

    esc_db = _escalations_db_path(request)

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


# ---------------------------------------------------------------------------
# 6. Blast Radius / Impact Assessment
# ---------------------------------------------------------------------------

@router.get("/impacted-decisions")
@router.get("/impact")
def impacted_decisions(
    request: Request,
    source: str = Query(..., min_length=1, description="Source document file name"),
    version: Optional[str] = Query(default=None, description="Optional document version"),
):
    """
    Find all past decisions whose claims were supported by evidence from a specific document.
    Enables the blast-radius highlight feature when a document changes.
    """
    drv = _get_neo4j_driver(request)
    if drv is not None:
        try:
            return neo4j_impacted_decisions(drv, source=source, version=version)
        except Exception as exc:
            logger.warning("Neo4j impacted_decisions failed: %s", exc)

    return {
        "source": source,
        "version": version,
        "doc_id": f"doc:{source}@{version}" if version else f"doc:{source}",
        "total_affected_decisions": 0,
        "affected_request_ids": [],
        "decisions": [],
    }


# ---------------------------------------------------------------------------
# 7. Calibration & Empirical Score Band (Feature #5)
# ---------------------------------------------------------------------------

@router.get("/calibration")
def get_score_calibration(
    score: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Answerability score to look up"),
):
    """
    Returns empirical calibration for an answerability score based on dev-set benchmark runs.
    Provides honest statements: 'Answers in this band were correct X of N times on the dev set'.
    """
    from app.core.calibration import get_calibration_for_score, get_calibration_summary

    if score is not None:
        return get_calibration_for_score(score)
    return get_calibration_summary()


# ---------------------------------------------------------------------------
# 8. Auditor Decision Report Export (Feature #7)
# ---------------------------------------------------------------------------

@router.get("/export/{request_id}")
def export_auditor_report(
    request: Request,
    request_id: str,
    format: str = Query(default="json", pattern="^(json|markdown|md)$"),
    download: bool = Query(default=False),
):
    """
    Download or view a complete audit report for a decision:
    question, answer, decision, scores, reasons, evidence and documents.
    """
    from app.audit.export import build_auditor_report, format_report_markdown

    report = build_auditor_report(request_id, request)

    filename = f"aegis_audit_{request_id}"
    if format in ("markdown", "md"):
        md_text = format_report_markdown(report)
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{filename}.md"'
        return PlainTextResponse(md_text, media_type="text/markdown", headers=headers)

    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}.json"'
    return JSONResponse(content=report, headers=headers)
