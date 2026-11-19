"""Named, parameterised read queries over the Decision Graph.

Each query returns flat rows; aggregation, thresholds and wording happen in
`app.intelligence.service`, so they can be unit-tested from canned rows.

Every query is scoped by `$prefix` (`request_id STARTS WITH $prefix`; the
empty string, the default, means all decisions).

Model compatibility. The current graph model (CONTRACTS.md section 3) adds
`Decision.created_at/topic/query_preview` and a `RETRIEVED` edge. Older
stored traces have none of these. Properties are therefore read as-is
(missing -> null) and the "evidence a decision considered" set is the
union of three stored links:

* `(d)-[:RETRIEVED]->(e)` -- new model;
* `(d)-[:HAS_CLAIM]->()-[:SUPPORTED_BY|CONTRADICTED_BY]->(e)` -- cited;
* Evidence whose id is request-scoped to the decision
  (`<request_id>:evidence:<i>`, the id `trace_builder` writes).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

#: Per-query transaction timeout (seconds) so no endpoint can hang on Neo4j.
QUERY_TIMEOUT_S = 5.0

_CONSIDERED_EVIDENCE = """
CALL {
  WITH d
  MATCH (d)-[:RETRIEVED]->(e:Evidence) RETURN e, 'retrieved' AS via
  UNION
  WITH d
  MATCH (d)-[:HAS_CLAIM]->(:Claim)-[:SUPPORTED_BY|CONTRADICTED_BY]->(e:Evidence)
  RETURN e, 'cited' AS via
  UNION
  WITH d
  MATCH (e:Evidence) WHERE e.id STARTS WITH d.request_id + ':evidence:'
  RETURN e, 'request_scoped' AS via
}
"""

QUERIES: Dict[str, str] = {
    # One row per Decision.
    "decision_overview": """
MATCH (d:Decision) WHERE d.request_id STARTS WITH $prefix
OPTIONAL MATCH (d)-[:BECAUSE]->(r:Reason)
WITH d, [c IN collect(DISTINCT r.code) WHERE c IS NOT NULL] AS reason_codes
OPTIONAL MATCH (d)-[:HAS_CLAIM]->(c:Claim)
RETURN d.request_id AS request_id, d.decision AS decision,
       d.created_at AS created_at, d.topic AS topic,
       d.query_preview AS query_preview, reason_codes,
       count(DISTINCT c) AS claims,
       count(DISTINCT CASE WHEN c.status = 'SUPPORTED' THEN c END) AS supported_claims
ORDER BY request_id
LIMIT $limit
""",
    # One row per (Decision, Document it considered).
    "decision_document_usage": """
MATCH (d:Decision) WHERE d.request_id STARTS WITH $prefix
""" + _CONSIDERED_EVIDENCE + """
MATCH (e)-[:FROM]->(doc:Document)
WHERE $doc_id IS NULL OR doc.id = $doc_id
WITH d, doc, collect(DISTINCT via) AS vias
OPTIONAL MATCH (d)-[:HAS_CLAIM]->(cs:Claim)-[:SUPPORTED_BY]->(:Evidence)-[:FROM]->(doc)
WHERE cs.status = 'SUPPORTED'
WITH d, doc, vias, collect(DISTINCT cs) AS supported
OPTIONAL MATCH (d)-[:HAS_CLAIM]->(cc:Claim)-[:CONTRADICTED_BY]->(:Evidence)-[:FROM]->(doc)
RETURN d.request_id AS request_id, d.decision AS decision,
       d.created_at AS created_at,
       doc.id AS doc_id, doc.source AS source, doc.version AS version,
       doc.date AS date, vias,
       size(supported) AS supported_by_doc,
       [x IN supported | x.text][..5] AS supported_claim_texts,
       count(DISTINCT cc) AS contradicted_by_doc
ORDER BY request_id, doc_id
LIMIT $limit
""",
    # One row per CONFLICTS_WITH edge between evidence of two documents,
    # with the decision the conflicting evidence belongs to.
    "conflict_edges": """
MATCH (e1:Evidence)-[c:CONFLICTS_WITH]->(e2:Evidence)
MATCH (e1)-[:FROM]->(d1:Document), (e2)-[:FROM]->(d2:Document)
WHERE d1.id <> d2.id
// A decision owns the conflict only if it retrieved BOTH passages (shared
// chunk ids can be retrieved by many decisions), else by request-scoped id.
OPTIONAL MATCH (dr:Decision)-[:RETRIEVED]->(e1)
WHERE (dr)-[:RETRIEVED]->(e2)
WITH e1, e2, c, d1, d2,
     coalesce(dr.request_id,
              CASE WHEN e1.id CONTAINS ':evidence:'
                   THEN split(e1.id, ':evidence:')[0] END) AS rid
MATCH (dec:Decision {request_id: rid})
WHERE dec.request_id STARTS WITH $prefix
RETURN DISTINCT dec.request_id AS request_id, dec.decision AS decision,
       d1.id AS doc_a, d1.source AS source_a,
       d2.id AS doc_b, d2.source AS source_b,
       c.kind AS kind, c.value_a AS value_a, c.value_b AS value_b
ORDER BY request_id
LIMIT $limit
""",
    "supersedes_edges": """
MATCH (n:Document)-[:SUPERSEDES]->(o:Document)
RETURN DISTINCT n.id AS newer, o.id AS older
LIMIT $limit
""",
    "documents": """
MATCH (doc:Document)
RETURN doc.id AS doc_id, doc.source AS source, doc.version AS version,
       doc.date AS date
ORDER BY doc_id
LIMIT $limit
""",
    # Escalations whose reasons point (via stored ABOUT edges) at evidence
    # from a document: directly, or through a claim that evidence contradicts.
    "escalation_root_causes": """
MATCH (d:Decision) WHERE d.decision = 'ESCALATE' AND d.request_id STARTS WITH $prefix
MATCH (d)-[:BECAUSE]->(r:Reason)
CALL {
  WITH r
  MATCH (r)-[:ABOUT]->(:Evidence)-[:FROM]->(doc:Document)
  RETURN doc, 'reason_about_evidence' AS path
  UNION
  WITH r
  MATCH (r)-[:ABOUT]->(:Claim)-[:CONTRADICTED_BY]->(:Evidence)-[:FROM]->(doc:Document)
  RETURN doc, 'reason_about_claim_contradicted_by' AS path
}
RETURN d.request_id AS request_id, r.code AS code,
       doc.id AS doc_id, doc.source AS source, doc.version AS version,
       collect(DISTINCT path) AS paths
ORDER BY request_id, doc_id
LIMIT $limit
""",
    "document_by_id": """
MATCH (doc:Document {id: $doc_id})
RETURN doc.id AS doc_id, doc.source AS source, doc.version AS version,
       doc.date AS date
LIMIT 1
""",
    "graph_decision_count": """
MATCH (d:Decision) WHERE d.request_id STARTS WITH $prefix
RETURN count(d) AS n
""",
}

#: Default row cap per query; far above demo scale, bounds worst case.
DEFAULT_ROW_LIMIT = 5000


def _with_timeout(work: Any) -> Any:
    """Attach the transaction timeout to a managed read unit of work.

    `neo4j.Query(..., timeout=)` is only accepted by `session.run`; inside
    `execute_read` the driver rejects it (TypeError), so the timeout is set
    with `neo4j.unit_of_work` instead.
    """
    try:
        from neo4j import unit_of_work  # type: ignore

        return unit_of_work(timeout=QUERY_TIMEOUT_S)(work)
    except Exception:  # neo4j not installed (fakes)
        return work


def _plain(value: Any) -> Any:
    """Neo4j temporal values -> ISO strings, so every row is JSON-ready."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    return value


def _to_dicts(result: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if result is None:
        return rows
    for rec in result:
        if hasattr(rec, "data"):
            rows.append(_plain(rec.data()))
        elif isinstance(rec, Mapping):
            rows.append(_plain(dict(rec)))
    return rows


def run(
    driver: Any,
    name: str,
    params: Optional[Dict[str, Any]] = None,
    database: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Run QUERIES[name] in a read transaction with a timeout.

    Exceptions propagate: the caller decides whether that means 503 or
    `graph.available: false`.
    """
    cypher = QUERIES[name]
    merged: Dict[str, Any] = {"prefix": "", "limit": DEFAULT_ROW_LIMIT, "doc_id": None}
    merged.update(params or {})
    session_kwargs = {"database": database} if database else {}
    with driver.session(**session_kwargs) as session:
        def work(tx: Any) -> List[Dict[str, Any]]:
            return _to_dicts(tx.run(cypher, merged))

        if hasattr(session, "execute_read"):
            return session.execute_read(_with_timeout(work))
        return _to_dicts(session.run(cypher, merged))
