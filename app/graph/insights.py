"""Insight queries across the Aegis Decision Graph.

Implements the five cross-decision analytical queries specified in
"Aegis Decision Graph (Neo4j Add-on): Team Brief" (Oct 22, 2026).

These queries aggregate across all past stored decisions to:
1. Identify most frequently conflicting document pairs.
2. Find outdated documents retrieved when newer versions exist.
3. Detect knowledge-base gaps ending in ABSTAIN.
4. Assess impact: find all past decisions relying on a specific document.
5. Group escalation tickets by root-cause document.

All functions return plain Python dictionaries (ready for JSON serialization
by Aaradhya's /v1/insights/* endpoints).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)


def _run_query(
    driver_or_session: Any,
    cypher: str,
    params: Optional[Dict[str, Any]] = None,
    database: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Execute a read Cypher query and return results as plain dicts.

    Supports driver instances, active sessions, and fake test drivers.
    """
    params = params or {}

    # If it's already a session:
    if hasattr(driver_or_session, "run") and not hasattr(driver_or_session, "session"):
        result = driver_or_session.run(cypher, **params)
        return _records_to_dicts(result)

    # If it's a driver:
    session_kwargs = {"database": database} if database else {}
    with driver_or_session.session(**session_kwargs) as session:
        if hasattr(session, "execute_read"):
            def _work(tx: Any) -> List[Dict[str, Any]]:
                res = tx.run(cypher, **params)
                return _records_to_dicts(res)
            return session.execute_read(_work)
        else:
            result = session.run(cypher, **params)
            return _records_to_dicts(result)


def _records_to_dicts(result: Any) -> List[Dict[str, Any]]:
    """Convert Cypher query results into plain dictionaries."""
    if result is None:
        return []
    records = []
    # If result is an iterable of records
    try:
        for rec in result:
            if hasattr(rec, "data"):
                records.append(rec.data())
            elif isinstance(rec, Mapping):
                records.append(dict(rec))
            elif isinstance(rec, (list, tuple)) and hasattr(result, "keys"):
                records.append(dict(zip(result.keys(), rec)))
            else:
                records.append(rec)
    except TypeError:
        pass
    return records


# ---------------------------------------------------------------------------
# 1. Which document pairs conflict most often?
# ---------------------------------------------------------------------------
def conflicting_document_pairs(
    driver: Any,
    limit: int = 10,
    database: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Find document pairs that conflict with each other most frequently.

    Follows: CONFLICTS_WITH between Evidence, then FROM to Document.
    Shows which documents in the corpus need fixing.
    """
    cypher = (
        "MATCH (e1:Evidence)-[c:CONFLICTS_WITH]->(e2:Evidence)\n"
        "MATCH (e1)-[:FROM]->(d1:Document)\n"
        "MATCH (e2)-[:FROM]->(d2:Document)\n"
        "WHERE d1.id < d2.id OR (d1.id = d2.id AND e1.id < e2.id)\n"
        "RETURN d1.source AS source_a,\n"
        "       d1.version AS version_a,\n"
        "       d1.id AS doc_a,\n"
        "       d2.source AS source_b,\n"
        "       d2.version AS version_b,\n"
        "       d2.id AS doc_b,\n"
        "       collect(DISTINCT c.kind) AS conflict_kinds,\n"
        "       count(c) AS conflict_count\n"
        "ORDER BY conflict_count DESC\n"
        "LIMIT $limit"
    )
    return _run_query(driver, cypher, {"limit": limit}, database=database)


# ---------------------------------------------------------------------------
# 2. Which documents are retrieved while a newer version exists?
# ---------------------------------------------------------------------------
def outdated_documents_retrieved(
    driver: Any,
    limit: int = 10,
    database: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Find documents retrieved in decisions while a newer version exists.

    Follows: SUPERSEDES with FROM.
    Shows which old versions should be retired.
    """
    cypher = (
        "MATCH (e:Evidence)-[:FROM]->(older:Document)<-[:SUPERSEDES]-(newer:Document)\n"
        "OPTIONAL MATCH (d:Decision)-[:HAS_CLAIM]->(:Claim)-[:SUPPORTED_BY|CONTRADICTED_BY]->(e)\n"
        "RETURN older.source AS source,\n"
        "       older.version AS outdated_version,\n"
        "       older.id AS outdated_doc_id,\n"
        "       newer.version AS newer_version,\n"
        "       newer.id AS newer_doc_id,\n"
        "       count(DISTINCT e) AS retrieved_chunk_count,\n"
        "       count(DISTINCT d) AS affected_decisions_count\n"
        "ORDER BY affected_decisions_count DESC, retrieved_chunk_count DESC\n"
        "LIMIT $limit"
    )
    return _run_query(driver, cypher, {"limit": limit}, database=database)


# ---------------------------------------------------------------------------
# 3. Which topics end in ABSTAIN most often?
# ---------------------------------------------------------------------------
def frequent_abstain_topics(
    driver: Any,
    limit: int = 10,
    database: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Find common failure reasons and claims in decisions that ended in ABSTAIN.

    Follows: Decision, Claim, with ABSTAIN reasons.
    Shows gaps in the knowledge base.
    """
    cypher = (
        "MATCH (d:Decision {decision: 'ABSTAIN'})\n"
        "OPTIONAL MATCH (d)-[:BECAUSE]->(r:Reason)\n"
        "OPTIONAL MATCH (d)-[:HAS_CLAIM]->(c:Claim)\n"
        "RETURN coalesce(r.code, 'NO_REASON') AS reason_code,\n"
        "       head(collect(DISTINCT r.message)) AS sample_reason,\n"
        "       collect(DISTINCT c.text)[..5] AS sample_claims,\n"
        "       collect(DISTINCT d.request_id)[..10] AS sample_request_ids,\n"
        "       count(DISTINCT d) AS abstain_count\n"
        "ORDER BY abstain_count DESC\n"
        "LIMIT $limit"
    )
    return _run_query(driver, cypher, {"limit": limit}, database=database)


# ---------------------------------------------------------------------------
# 4. If this document is wrong, which past decisions relied on it?
# ---------------------------------------------------------------------------
def impacted_decisions_for_document(
    driver: Any,
    source: str,
    version: Optional[str] = None,
    database: Optional[str] = None,
) -> Dict[str, Any]:
    """Find all past decisions whose claims were supported by evidence from a document.

    Follows: Document back to Evidence, Claim, Decision.
    Answers the judge question: "What if the evidence itself is wrong?"
    """
    cypher = (
        "MATCH (doc:Document)\n"
        "WHERE doc.source = $source AND ($version IS NULL OR doc.version = $version)\n"
        "MATCH (e:Evidence)-[:FROM]->(doc)\n"
        "MATCH (c:Claim)-[:SUPPORTED_BY]->(e)\n"
        "MATCH (d:Decision)-[:HAS_CLAIM]->(c)\n"
        "RETURN doc.source AS source,\n"
        "       doc.version AS version,\n"
        "       doc.id AS doc_id,\n"
        "       collect(DISTINCT d.request_id) AS affected_request_ids,\n"
        "       collect(DISTINCT {\n"
        "           request_id: d.request_id,\n"
        "           decision: d.decision,\n"
        "           score: d.answerability_score\n"
        "       }) AS decisions,\n"
        "       count(DISTINCT d) AS total_affected_decisions"
    )
    results = _run_query(
        driver,
        cypher,
        {"source": source, "version": version},
        database=database,
    )
    if results:
        row = results[0]
        return {
            "source": row.get("source", source),
            "version": row.get("version", version),
            "doc_id": row.get("doc_id"),
            "total_affected_decisions": row.get("total_affected_decisions", 0),
            "affected_request_ids": row.get("affected_request_ids", []),
            "decisions": row.get("decisions", []),
        }

    return {
        "source": source,
        "version": version,
        "doc_id": None,
        "total_affected_decisions": 0,
        "affected_request_ids": [],
        "decisions": [],
    }


# ---------------------------------------------------------------------------
# 5. Which escalations share one root cause?
# ---------------------------------------------------------------------------
def escalations_by_root_cause(
    driver: Any,
    limit: int = 10,
    database: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Group escalated decisions by the conflicting/stale root-cause document.

    Follows: BECAUSE and ABOUT, grouped by Document.
    A reviewer fixes one document, not twenty tickets.
    """
    cypher = (
        "MATCH (d:Decision {decision: 'ESCALATE'})-[:BECAUSE]->(r:Reason)-[:ABOUT]->(e:Evidence)-[:FROM]->(doc:Document)\n"
        "RETURN doc.source AS source,\n"
        "       doc.version AS version,\n"
        "       doc.id AS doc_id,\n"
        "       r.code AS root_cause_code,\n"
        "       collect(DISTINCT r.message)[..3] AS sample_messages,\n"
        "       collect(DISTINCT d.request_id) AS escalation_request_ids,\n"
        "       count(DISTINCT d) AS escalation_count\n"
        "ORDER BY escalation_count DESC\n"
        "LIMIT $limit"
    )
    return _run_query(driver, cypher, {"limit": limit}, database=database)
