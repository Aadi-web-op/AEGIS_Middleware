"""Neo4jGraphSink: writes an agreed decision trace into Neo4j.

What this module does *not* do is as important as what it does. It does
not decide anything, does not run a signal, does not apply policy and
does not regenerate a trace -- it consumes the trace it is handed. It is
also never on the decision path: see `app.graph.sink.safe_write_trace`.

Idempotency
-----------
Every statement is a `MERGE`. A Decision is merged on `request_id`
(team brief, rule 3); every other node on its `(label, id)` pair; every
relationship on its `(start, type, end)` pattern, plus `kind` for
CONFLICTS_WITH so that a numeric and a statement conflict between the
same two passages stay distinct edges. Writing the same trace twice
therefore produces the same graph as writing it once.

Cypher safety
-------------
Property names and values are always passed as parameters. The only
things interpolated into a query string are node labels and relationship
types, because Cypher cannot parameterise them -- and those come from the
closed allow-lists in `app.graph.contract`, never from trace content. A
label or relationship type that is not on the list makes the write fail
instead of reaching the database.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.graph.contract import (
    CLAIM_TEXT_CHARS,
    EVIDENCE_PREVIEW_CHARS,
    TraceContractError,
    is_node_type,
    is_relationship_type,
    preview_keys,
    strip_retrieved_text,
    truncate_preview,
    validate_trace,
)

logger = logging.getLogger(__name__)

Statement = Tuple[str, Dict[str, Any]]

# Node types whose text content came from a retrieved document and so must
# never be stored in full (team brief, rule 7).
_RETRIEVED_NODE_TYPES = frozenset({"Evidence", "Document"})

# Keys that carry identity or structure rather than a stored property.
_STRUCTURAL_NODE_KEYS = frozenset({"id", "type"})
_STRUCTURAL_EDGE_KEYS = frozenset({"type", "from", "to"})

# Relationship types that may legitimately exist more than once between the
# same pair of nodes, distinguished by `kind`.
_KIND_SCOPED_RELATIONSHIPS = frozenset({"CONFLICTS_WITH"})


def _is_storable(value: Any) -> bool:
    """True when Neo4j can hold `value` as a property."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return True
    if isinstance(value, (list, tuple)):
        return all(
            item is None or isinstance(item, (str, bool, int, float))
            for item in value
        )
    return False


class Neo4jGraphSink:
    """Persists decision traces to Neo4j via an injected driver.

    The driver is injected, never constructed here, so tests run against
    a fake and never need a server. `from_uri` is the convenience that
    builds a real driver, and it imports `neo4j` lazily so this module
    imports cleanly when the package is not installed.
    """

    def __init__(
        self,
        driver: Any,
        database: Optional[str] = None,
    ) -> None:
        if driver is None:
            raise ValueError("Neo4jGraphSink requires a driver")
        self._driver = driver
        self._database = database
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------------
    @classmethod
    def from_uri(
        cls,
        uri: str,
        user: str,
        password: str,
        database: Optional[str] = None,
    ) -> "Neo4jGraphSink":
        """Build a sink against a real Neo4j. Not used by any test."""
        from neo4j import GraphDatabase  # imported lazily: optional dependency

        driver = GraphDatabase.driver(uri, auth=(user, password))
        return cls(driver, database=database)

    def close(self) -> None:
        """Close the injected driver, if it supports closing."""
        closer = getattr(self._driver, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                logger.exception("Closing the Neo4j driver failed")

    # ------------------------------------------------------------------
    # statement construction (pure -- no driver involved)
    # ------------------------------------------------------------------
    def build_statements(self, trace: Mapping[str, Any]) -> List[Statement]:
        """Turn a trace into parameterised Cypher statements.

        Pure and deterministic: the same trace always yields the same
        statements in the same order. Raises `TraceContractError` for a
        trace that cannot be stored safely.
        """
        clean = validate_trace(trace)
        request_id = clean["request_id"]

        statements: List[Statement] = []
        for node in clean["nodes"]:
            statements.append(self._node_statement(node, request_id))
        for edge in clean["edges"]:
            statements.append(self._edge_statement(edge, clean["nodes"]))
        return statements

    def _node_statement(self, node: Mapping[str, Any], request_id: str) -> Statement:
        node_type = node["type"]
        if not is_node_type(node_type):  # defence in depth; validate_trace checks too
            raise TraceContractError(f"refusing to write node label {node_type!r}")

        props = self._node_properties(node, node_type)

        if node_type == "Decision":
            # Rule 3: request_id is the Decision's identity, whatever else
            # the trace carries. `id` is kept as a property so that edges can
            # match every node type uniformly on {id: ...} -- and it has to be
            # the node's *own* id, because that is the name the trace's edges
            # use. Overwriting it with the request_id is a silent data loss:
            # `MATCH (a:Decision {id: ...})` would then find no row, Cypher
            # skips the MERGE without raising, and the write reports success
            # with every HAS_CLAIM and BECAUSE edge missing.
            props["request_id"] = request_id
            props["id"] = node["id"]
            if node["id"] != request_id:
                logger.warning(
                    "Decision node id %r is not the request_id %r; merging on "
                    "the request_id per contract rule 3 and storing the node's "
                    "own id, so this trace's Decision edges still resolve",
                    node["id"],
                    request_id,
                )
            cypher = (
                "MERGE (n:Decision {request_id: $merge_key})\n"
                "SET n += $props"
            )
            return cypher, {"merge_key": request_id, "props": props}

        props["id"] = node["id"]
        cypher = (
            f"MERGE (n:{node_type} {{id: $merge_key}})\n"
            "SET n += $props"
        )
        return cypher, {"merge_key": node["id"], "props": props}

    def _node_properties(
        self, node: Mapping[str, Any], node_type: str
    ) -> Dict[str, Any]:
        """Select, cap and sanitise the properties stored on a node."""
        raw = {k: v for k, v in node.items() if k not in _STRUCTURAL_NODE_KEYS}

        if node_type in _RETRIEVED_NODE_TYPES:
            raw, dropped = strip_retrieved_text(raw)
            if dropped:
                logger.debug(
                    "Dropped %s from %s node %s: full retrieved text is not persisted",
                    ", ".join(sorted(dropped)),
                    node_type,
                    node.get("id"),
                )

        # Every preview is capped, on every node type, every time.
        for key in preview_keys(list(raw)):
            raw[key] = truncate_preview(raw[key], EVIDENCE_PREVIEW_CHARS)

        if node_type == "Claim" and isinstance(raw.get("text"), str):
            # Answer-derived, not retrieved, so it is stored -- but bounded.
            raw["text"] = raw["text"][:CLAIM_TEXT_CHARS]

        return self._storable(raw, f"{node_type} node {node.get('id')!r}")

    def _edge_statement(
        self, edge: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]]
    ) -> Statement:
        rel_type = edge["type"]
        if not is_relationship_type(rel_type):
            raise TraceContractError(f"refusing to write relationship {rel_type!r}")

        labels = {node["id"]: node["type"] for node in nodes}
        start_label = labels[edge["from"]]
        end_label = labels[edge["to"]]
        if not (is_node_type(start_label) and is_node_type(end_label)):
            raise TraceContractError(
                f"edge {rel_type} connects an unknown node label"
            )

        props = self._storable(
            {k: v for k, v in edge.items() if k not in _STRUCTURAL_EDGE_KEYS},
            f"{rel_type} edge {edge['from']}->{edge['to']}",
        )

        params: Dict[str, Any] = {
            "from_id": edge["from"],
            "to_id": edge["to"],
            "props": props,
        }

        # A pair of passages can conflict numerically *and* by statement.
        # Keying the MERGE on `kind` keeps those as two edges while still
        # being idempotent for each of them.
        if rel_type in _KIND_SCOPED_RELATIONSHIPS and edge.get("kind") is not None:
            merge_pattern = f"MERGE (a)-[r:{rel_type} {{kind: $kind}}]->(b)"
            params["kind"] = edge["kind"]
        else:
            merge_pattern = f"MERGE (a)-[r:{rel_type}]->(b)"

        cypher = (
            f"MATCH (a:{start_label} {{id: $from_id}})\n"
            f"MATCH (b:{end_label} {{id: $to_id}})\n"
            f"{merge_pattern}\n"
            "SET r += $props"
        )
        return cypher, params

    @staticmethod
    def _storable(props: Mapping[str, Any], what: str) -> Dict[str, Any]:
        """Drop properties Neo4j cannot store, rather than stringifying them."""
        kept: Dict[str, Any] = {}
        for key, value in props.items():
            if _is_storable(value):
                kept[key] = value
            else:
                logger.debug(
                    "Dropped unstorable property %r (%s) from %s",
                    key,
                    type(value).__name__,
                    what,
                )
        return kept

    # ------------------------------------------------------------------
    # writing
    # ------------------------------------------------------------------
    def write_trace(self, trace: Mapping[str, Any]) -> bool:
        """Write a trace. Returns True on success, False on any failure.

        Never raises. All statements run in one write transaction, so a
        failure part-way through leaves no half-written decision behind.
        """
        request_id = "<unknown>"
        try:
            statements = self.build_statements(trace)
            request_id = str(trace.get("request_id", request_id))
        except TraceContractError as exc:
            self.last_error = str(exc)
            logger.error(
                "Rejected a malformed trace before writing: %s", exc
            )
            return False
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("Could not build Cypher for a trace")
            return False

        if not statements:
            logger.debug("Trace %s produced no statements; nothing to write", request_id)
            self.last_error = None
            return True

        session_kwargs: Dict[str, Any] = {}
        if self._database:
            session_kwargs["database"] = self._database

        try:
            with self._driver.session(**session_kwargs) as session:
                session.execute_write(self._run_all, statements)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "Neo4j write failed for request %s after %d statement(s); "
                "the decision and its trace are unaffected",
                request_id,
                len(statements),
            )
            return False

        self.last_error = None
        logger.debug(
            "Wrote %d statement(s) to the decision graph for request %s",
            len(statements),
            request_id,
        )
        return True

    @staticmethod
    def _run_all(tx: Any, statements: Sequence[Statement]) -> None:
        for cypher, params in statements:
            tx.run(cypher, **params)
