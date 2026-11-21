"""Read side of the decision graph: the queries behind `/v1/graph/*`.

Cypher safety
-------------
Every query below is a module-level constant. Nothing from a request is
ever formatted into a query string: request values travel only as `$`
parameters. The two status queries are generated, but only from the
closed allow-lists in `app.graph.contract`. Relationship types are
additionally restricted at run time with `type(r) IN $rel_types`, and
nodes whose label is not on the allow-list are dropped from the result,
so foreign data living in the same database never leaks through.

Shapes
------
Subgraphs are `{"nodes": [...], "edges": [...]}` with

    node: {"id", "type", "label", "props"}
    edge: {"id": "from|TYPE|to|kind", "type", "from", "to", "props"}

A node's id is its stored `id` property (for a Decision that is the
request_id), which is also what edges reference.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.graph.contract import DECISIONS, NODE_TYPES, RELATIONSHIP_TYPES

logger = logging.getLogger(__name__)

LABEL_TEXT_CHARS = 60
MAX_LIMIT = 500

# Decision -> Evidence, either directly (RETRIEVED, trace v2) or through a
# claim (v1 traces written before RETRIEVED existed).
_TO_EVIDENCE = "[:RETRIEVED|HAS_CLAIM|SUPPORTED_BY|CONTRADICTED_BY*1..2]"

STATUS_NODES_CYPHER = "RETURN " + ", ".join(
    f"COUNT {{ (:{label}) }} AS {label}" for label in NODE_TYPES
)
STATUS_RELATIONSHIPS_CYPHER = "RETURN " + ", ".join(
    f"COUNT {{ ()-[:{rel}]->() }} AS {rel}" for rel in RELATIONSHIP_TYPES
)

LIST_DECISIONS_CYPHER = f"""
MATCH (d:Decision)
WHERE ($request_id IS NULL OR d.request_id = $request_id)
  AND ($decision IS NULL OR d.decision = $decision)
  AND ($source IS NULL OR EXISTS {{
        MATCH (d)-{_TO_EVIDENCE}->(:Evidence)-[:FROM]->(s:Document)
        WHERE s.source = $source }})
WITH d
ORDER BY d.created_at IS NULL, d.created_at DESC, d.request_id
LIMIT $limit
RETURN d.request_id AS request_id,
       d.decision AS decision,
       d.created_at AS created_at,
       d.query_preview AS query_preview,
       d.topic AS topic,
       d.answerability_score AS answerability_score,
       d.headline AS headline,
       d.degraded AS degraded,
       d.profile AS profile,
       d.policy_version AS policy_version,
       COUNT {{ (d)-[:HAS_CLAIM]->(:Claim) }} AS claim_count,
       COUNT {{ MATCH (d)-{_TO_EVIDENCE}->(e:Evidence) RETURN DISTINCT e }} AS evidence_count,
       COUNT {{ MATCH (d)-{_TO_EVIDENCE}->(:Evidence)-[:FROM]->(doc:Document)
               RETURN DISTINCT doc }} AS document_count,
       [(d)-[:BECAUSE]->(r:Reason) | r.code] AS reason_codes
ORDER BY created_at IS NULL, created_at DESC, request_id
"""

DECISION_SUBGRAPH_CYPHER = f"""
MATCH (d:Decision {{request_id: $request_id}})
CALL (d) {{
  OPTIONAL MATCH (d)-[:HAS_CLAIM]->(c:Claim)
  RETURN collect(DISTINCT c) AS claims
}}
CALL (d) {{
  OPTIONAL MATCH (d)-[:BECAUSE]->(r:Reason)
  RETURN collect(DISTINCT r) AS reasons
}}
CALL (d) {{
  OPTIONAL MATCH (d)-{_TO_EVIDENCE}->(e:Evidence)
  RETURN collect(DISTINCT e) AS evidence
}}
CALL (evidence) {{
  UNWIND evidence AS e
  OPTIONAL MATCH (e)-[:FROM]->(doc:Document)
  RETURN collect(DISTINCT doc) AS documents
}}
WITH [d] + claims + reasons + evidence + documents AS ns
CALL (ns) {{
  UNWIND ns AS a
  MATCH (a)-[r]->(b)
  WHERE b IN ns AND type(r) IN $rel_types
  RETURN collect(DISTINCT {{
    type: type(r),
    from: coalesce(a.id, a.request_id),
    to: coalesce(b.id, b.request_id),
    props: properties(r)
  }}) AS edges
}}
RETURN [n IN ns | {{labels: labels(n), props: properties(n)}}] AS nodes, edges
"""

LIST_DOCUMENTS_CYPHER = f"""
MATCH (doc:Document)
WITH doc
ORDER BY doc.source, doc.version, doc.id
LIMIT $limit
RETURN doc.id AS doc_id,
       doc.source AS source,
       doc.version AS version,
       doc.date AS date,
       COUNT {{ MATCH (dec:Decision)-{_TO_EVIDENCE}->(:Evidence)-[:FROM]->(doc)
               RETURN DISTINCT dec }} AS decision_count,
       COUNT {{ MATCH (c:Claim)-[:SUPPORTED_BY]->(:Evidence)-[:FROM]->(doc)
               RETURN DISTINCT c }} AS supported_claim_count,
       COUNT {{ MATCH (c:Claim)-[:CONTRADICTED_BY]->(:Evidence)-[:FROM]->(doc)
               RETURN DISTINCT c }} AS contradicted_claim_count,
       COUNT {{ MATCH (:Evidence)-[k:CONFLICTS_WITH]-(:Evidence)-[:FROM]->(doc)
               RETURN DISTINCT k }} AS conflict_count,
       [(newer:Document)-[:SUPERSEDES]->(doc) | newer.id] AS superseded_by,
       [(doc)-[:SUPERSEDES]->(older:Document) | older.id] AS supersedes
ORDER BY source, version, doc_id
"""

# One branch per label so each lookup uses that label's unique index
# instead of scanning every node for an `id`.
NEIGHBORS_CYPHER = """
CALL {
  MATCH (n:Decision {request_id: $node_id}) RETURN n
  UNION
  MATCH (n:Decision {id: $node_id}) RETURN n
  UNION
  MATCH (n:Claim {id: $node_id}) RETURN n
  UNION
  MATCH (n:Evidence {id: $node_id}) RETURN n
  UNION
  MATCH (n:Document {id: $node_id}) RETURN n
  UNION
  MATCH (n:Reason {id: $node_id}) RETURN n
}
WITH n LIMIT 1
CALL (n) {
  OPTIONAL MATCH (n)-[r]-(m)
  WHERE type(r) IN $rel_types
  WITH r, m
  ORDER BY type(r), coalesce(m.id, m.request_id)
  LIMIT $limit
  RETURN collect(CASE WHEN r IS NULL THEN null ELSE {
    type: type(r),
    from: coalesce(startNode(r).id, startNode(r).request_id),
    to: coalesce(endNode(r).id, endNode(r).request_id),
    props: properties(r),
    labels: labels(m),
    node: properties(m)
  } END) AS rels
}
RETURN labels(n) AS labels, properties(n) AS props, rels
"""

ALL_READ_QUERIES: Dict[str, str] = {
    "status_nodes": STATUS_NODES_CYPHER,
    "status_relationships": STATUS_RELATIONSHIPS_CYPHER,
    "list_decisions": LIST_DECISIONS_CYPHER,
    "decision_subgraph": DECISION_SUBGRAPH_CYPHER,
    "list_documents": LIST_DOCUMENTS_CYPHER,
    "neighbors": NEIGHBORS_CYPHER,
}

_NODE_TYPE_SET = frozenset(NODE_TYPES)
_REL_TYPE_SET = frozenset(RELATIONSHIP_TYPES)


# ---------------------------------------------------------------------------
# value / shape helpers
# ---------------------------------------------------------------------------
def _json_safe(value: Any) -> Any:
    """Make a Neo4j value JSON-serialisable (temporal types become strings)."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    return str(value)


def _shorten(text: Any, limit: int = LABEL_TEXT_CHARS) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _node_type(labels: Optional[Iterable[Any]]) -> Optional[str]:
    for label in labels or ():
        if label in _NODE_TYPE_SET:
            return label
    return None


def display_label(node_type: str, props: Mapping[str, Any]) -> str:
    """Short text a UI can print on a node."""
    if node_type == "Decision":
        decision = props.get("decision") or "Decision"
        score = props.get("answerability_score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            return f"{decision} · {score:.2f}"
        return str(decision)
    if node_type == "Claim":
        return _shorten(props.get("text") or "Claim")
    if node_type == "Evidence":
        if props.get("preview"):
            return _shorten(props["preview"])
        source = props.get("source") or "Evidence"
        index = props.get("evidence_index")
        return f"{source}#{index}" if index is not None else str(source)
    if node_type == "Document":
        source = props.get("source") or props.get("id") or "Document"
        version = props.get("version")
        return f"{source}@{version}" if version else str(source)
    if node_type == "Reason":
        return str(props.get("code") or "Reason")
    return node_type


def make_node(labels: Optional[Iterable[Any]], props: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Shape a node for the API, or None if it is not an allow-listed node."""
    node_type = _node_type(labels)
    if node_type is None or not isinstance(props, Mapping):
        return None
    node_id = props.get("id") or props.get("request_id")
    if not isinstance(node_id, str) or not node_id:
        return None
    safe = _json_safe(props)
    return {
        "id": node_id,
        "type": node_type,
        "label": display_label(node_type, safe),
        "props": safe,
    }


def make_edge(raw: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Shape a relationship for the API, or None if it is not allow-listed."""
    if not isinstance(raw, Mapping):
        return None
    rel_type, start, end = raw.get("type"), raw.get("from"), raw.get("to")
    if rel_type not in _REL_TYPE_SET or not isinstance(start, str) or not isinstance(end, str):
        return None
    props = _json_safe(raw.get("props") or {})
    kind = props.get("kind") or ""
    return {
        "id": f"{start}|{rel_type}|{end}|{kind}",
        "type": rel_type,
        "from": start,
        "to": end,
        "props": props,
    }


def _dedupe(items: Iterable[Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if item is not None:
            seen.setdefault(item["id"], item)
    return list(seen.values())


def _clamp(limit: Any, default: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(MAX_LIMIT, value))


# ---------------------------------------------------------------------------
# reader
# ---------------------------------------------------------------------------
class GraphReader:
    """Runs the read queries against an injected driver.

    Methods raise whatever the driver raises (the routes turn that into a
    503); they never write.
    """

    def __init__(self, driver: Any, database: Optional[str] = None) -> None:
        if driver is None:
            raise ValueError("GraphReader requires a driver")
        self._driver = driver
        self._database = database

    def _read(self, cypher: str, params: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        params = dict(params or {})

        def _work(tx: Any) -> List[Dict[str, Any]]:
            result = tx.run(cypher, **params)
            rows: List[Dict[str, Any]] = []
            for record in result or ():
                rows.append(record.data() if hasattr(record, "data") else dict(record))
            return rows

        session_kwargs = {"database": self._database} if self._database else {}
        with self._driver.session(**session_kwargs) as session:
            if hasattr(session, "execute_read"):
                return session.execute_read(_work)
            return _work(session)

    # -- status ---------------------------------------------------------
    def counts(self) -> Dict[str, Dict[str, int]]:
        """Node and relationship counts per allow-listed label/type."""
        nodes = self._read(STATUS_NODES_CYPHER)
        rels = self._read(STATUS_RELATIONSHIPS_CYPHER)
        node_row = nodes[0] if nodes else {}
        rel_row = rels[0] if rels else {}
        return {
            "counts": {label: int(node_row.get(label) or 0) for label in NODE_TYPES},
            "relationships": {
                rel: int(rel_row.get(rel) or 0) for rel in RELATIONSHIP_TYPES
            },
        }

    # -- decisions --------------------------------------------------------
    @staticmethod
    def _decision_item(row: Mapping[str, Any]) -> Dict[str, Any]:
        item = _json_safe(dict(row))
        item["reason_codes"] = [c for c in (item.get("reason_codes") or []) if c]
        for key in ("claim_count", "evidence_count", "document_count"):
            item[key] = int(item.get(key) or 0)
        return item

    def list_decisions(
        self,
        limit: int = 50,
        decision: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Stored decisions, newest first, optionally filtered."""
        if decision is not None and decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        rows = self._read(
            LIST_DECISIONS_CYPHER,
            {
                "request_id": None,
                "decision": decision or None,
                "source": source or None,
                "limit": _clamp(limit, 50),
            },
        )
        return [self._decision_item(row) for row in rows]

    def decision_summary(self, request_id: str) -> Optional[Dict[str, Any]]:
        rows = self._read(
            LIST_DECISIONS_CYPHER,
            {"request_id": request_id, "decision": None, "source": None, "limit": 1},
        )
        return self._decision_item(rows[0]) if rows else None

    def decision_subgraph(self, request_id: str) -> Optional[Dict[str, Any]]:
        """A decision's claims, evidence, documents and reasons, or None."""
        summary = self.decision_summary(request_id)
        if summary is None:
            return None
        rows = self._read(
            DECISION_SUBGRAPH_CYPHER,
            {"request_id": request_id, "rel_types": list(RELATIONSHIP_TYPES)},
        )
        row = rows[0] if rows else {}
        nodes = _dedupe(
            make_node(n.get("labels"), n.get("props"))
            for n in (row.get("nodes") or [])
            if isinstance(n, Mapping)
        )
        node_ids = {n["id"] for n in nodes}
        edges = [
            e
            for e in _dedupe(make_edge(e) for e in (row.get("edges") or []))
            if e["from"] in node_ids and e["to"] in node_ids
        ]
        return {"decision": summary, "nodes": nodes, "edges": edges}

    # -- documents --------------------------------------------------------
    def list_documents(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self._read(LIST_DOCUMENTS_CYPHER, {"limit": _clamp(limit, 100)})
        items: List[Dict[str, Any]] = []
        for row in rows:
            item = _json_safe(dict(row))
            for key in (
                "decision_count",
                "supported_claim_count",
                "contradicted_claim_count",
                "conflict_count",
            ):
                item[key] = int(item.get(key) or 0)
            for key in ("superseded_by", "supersedes"):
                item[key] = sorted({v for v in (item.get(key) or []) if v})
            items.append(item)
        return items

    # -- neighbours -------------------------------------------------------
    def neighbors(self, node_id: str, limit: int = 50) -> Optional[Dict[str, Any]]:
        """One-hop subgraph around a node, or None when the node is absent."""
        rows = self._read(
            NEIGHBORS_CYPHER,
            {
                "node_id": node_id,
                "rel_types": list(RELATIONSHIP_TYPES),
                "limit": _clamp(limit, 50),
            },
        )
        if not rows:
            return None
        row = rows[0]
        center = make_node(row.get("labels"), row.get("props"))
        if center is None:
            return None
        nodes: List[Optional[Dict[str, Any]]] = [center]
        edges: List[Optional[Dict[str, Any]]] = []
        for rel in row.get("rels") or []:
            if not isinstance(rel, Mapping):
                continue
            other = make_node(rel.get("labels"), rel.get("node"))
            edge = make_edge(rel)
            if other is None or edge is None:
                continue
            nodes.append(other)
            edges.append(edge)
        return {"center": center["id"], "nodes": _dedupe(nodes), "edges": _dedupe(edges)}
