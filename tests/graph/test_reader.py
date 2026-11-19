"""GraphReader: Cypher safety and result shaping (fake driver)."""

from __future__ import annotations

import re

import pytest

from app.graph.contract import NODE_TYPES, RELATIONSHIP_TYPES
from app.graph.reader import (
    ALL_READ_QUERIES,
    DECISION_SUBGRAPH_CYPHER,
    LIST_DECISIONS_CYPHER,
    LIST_DOCUMENTS_CYPHER,
    MAX_LIMIT,
    NEIGHBORS_CYPHER,
    STATUS_NODES_CYPHER,
    GraphReader,
    display_label,
    make_edge,
    make_node,
)
from tests.graph.fake_driver import FakeReadDriver

HOSTILE = "x'}) DETACH DELETE n //"

DECISION_ROW = {
    "request_id": "r1",
    "decision": "ESCALATE",
    "created_at": "2026-11-17T10:00:00+00:00",
    "query_preview": "How many leave days?",
    "topic": "day|leave",
    "answerability_score": 0.41,
    "headline": "h",
    "degraded": False,
    "profile": "standard",
    "policy_version": "0.1.0",
    "claim_count": 1,
    "evidence_count": 2,
    "document_count": 2,
    "reason_codes": ["CONTRADICTION", None],
}

SUBGRAPH_ROW = {
    "nodes": [
        {"labels": ["Decision"], "props": {"id": "r1", "request_id": "r1", "decision": "ESCALATE", "answerability_score": 0.41}},
        {"labels": ["Claim"], "props": {"id": "r1:claim:0", "text": "Employees receive 18 casual leaves. " * 5, "status": "CONTRADICTED"}},
        {"labels": ["Evidence"], "props": {"id": "r1:evidence:0", "preview": "18 leaves", "source": "hr.pdf"}},
        {"labels": ["Document"], "props": {"id": "doc:hr.pdf@v2", "source": "hr.pdf", "version": "v2"}},
        {"labels": ["Document"], "props": {"id": "doc:hr.pdf@v1", "source": "hr.pdf", "version": "v1"}},
        {"labels": ["Reason"], "props": {"id": "r1:reason:0", "code": "CONTRADICTION", "message": "m"}},
        {"labels": ["Secret"], "props": {"id": "s1", "password": "hunter2"}},
    ],
    "edges": [
        {"type": "HAS_CLAIM", "from": "r1", "to": "r1:claim:0", "props": {}},
        {"type": "CONFLICTS_WITH", "from": "r1:evidence:0", "to": "r1:evidence:0", "props": {"kind": "numeric"}},
        {"type": "SUPERSEDES", "from": "doc:hr.pdf@v2", "to": "doc:hr.pdf@v1", "props": {}},
        {"type": "OWNS", "from": "r1", "to": "s1", "props": {}},
        {"type": "RETRIEVED", "from": "r1", "to": "not-in-subgraph", "props": {}},
    ],
}


def _responder(cypher, params):
    if cypher == LIST_DECISIONS_CYPHER:
        if params.get("request_id") not in (None, "r1"):
            return []
        return [dict(DECISION_ROW)]
    if cypher == DECISION_SUBGRAPH_CYPHER:
        return [SUBGRAPH_ROW]
    if cypher == LIST_DOCUMENTS_CYPHER:
        return [
            {
                "doc_id": "doc:hr.pdf@v1", "source": "hr.pdf", "version": "v1", "date": None,
                "decision_count": 3, "supported_claim_count": 1,
                "contradicted_claim_count": 2, "conflict_count": None,
                "superseded_by": ["doc:hr.pdf@v2", "doc:hr.pdf@v2"], "supersedes": [],
            }
        ]
    if cypher == NEIGHBORS_CYPHER:
        if params["node_id"] != "doc:hr.pdf@v1":
            return []
        return [
            {
                "labels": ["Document"],
                "props": {"id": "doc:hr.pdf@v1", "source": "hr.pdf", "version": "v1"},
                "rels": [
                    {"type": "FROM", "from": "r1:evidence:0", "to": "doc:hr.pdf@v1", "props": {},
                     "labels": ["Evidence"], "node": {"id": "r1:evidence:0", "source": "hr.pdf", "evidence_index": 0}},
                    {"type": "OWNS", "from": "x", "to": "doc:hr.pdf@v1", "props": {},
                     "labels": ["Other"], "node": {"id": "x"}},
                ],
            }
        ]
    if cypher == STATUS_NODES_CYPHER:
        return [{label: 2 for label in NODE_TYPES}]
    return [{rel: 1 for rel in RELATIONSHIP_TYPES}]


@pytest.fixture
def driver():
    return FakeReadDriver(_responder)


@pytest.fixture
def reader(driver):
    return GraphReader(driver)


# ---------------------------------------------------------------------------
# Cypher safety
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(ALL_READ_QUERIES))
def test_read_queries_never_write(name):
    cypher = ALL_READ_QUERIES[name].upper()
    for keyword in ("CREATE", "MERGE", "DELETE", "REMOVE", "DROP", "LOAD", "SET", "FOREACH"):
        assert not re.search(rf"\b{keyword}\b", cypher), f"{name} contains {keyword}"


@pytest.mark.parametrize("name", sorted(ALL_READ_QUERIES))
def test_read_queries_only_name_allow_listed_labels_and_types(name):
    cypher = ALL_READ_QUERIES[name]
    # Labels: `(x:Label` / `(:Label`.
    for label in re.findall(r"\(\w*:(\w+)", cypher):
        assert label in NODE_TYPES, f"{name} names label {label}"
    # Relationship types: `[x:TYPE|TYPE...]`.
    for group in re.findall(r"\[\w*:([A-Z_|]+)", cypher):
        for rel in group.split("|"):
            assert rel in RELATIONSHIP_TYPES, f"{name} names relationship {rel}"


def test_request_values_travel_only_as_parameters(reader, driver):
    reader.list_decisions(limit=5, source=HOSTILE)
    reader.decision_subgraph(HOSTILE)
    reader.neighbors(HOSTILE, limit=5)

    assert driver.queries, "queries were issued"
    constants = set(ALL_READ_QUERIES.values())
    for call in driver.queries:
        assert call.cypher in constants, "only the constant query strings are ever run"
        assert HOSTILE not in call.cypher
    assert any(HOSTILE in map(str, call.params.values()) for call in driver.queries)


def test_relationship_types_are_restricted_by_parameter(reader, driver):
    reader.neighbors("doc:hr.pdf@v1")
    call = driver.queries[-1]
    assert call.params["rel_types"] == list(RELATIONSHIP_TYPES)
    assert "type(r) IN $rel_types" in call.cypher


def test_limits_are_clamped(reader, driver):
    reader.list_decisions(limit=10**9)
    assert driver.queries[-1].params["limit"] == MAX_LIMIT
    reader.list_documents(limit=-5)
    assert driver.queries[-1].params["limit"] == 1
    reader.neighbors("doc:hr.pdf@v1", limit="junk")
    assert driver.queries[-1].params["limit"] == 50


def test_an_unknown_decision_filter_is_rejected_before_any_query(reader, driver):
    with pytest.raises(ValueError):
        reader.list_decisions(decision="DROP")
    assert driver.queries == []


def test_the_reader_requires_a_driver():
    with pytest.raises(ValueError):
        GraphReader(None)


# ---------------------------------------------------------------------------
# shaping
# ---------------------------------------------------------------------------
def test_counts_cover_every_label_and_type(reader):
    counts = reader.counts()
    assert counts["counts"] == {label: 2 for label in NODE_TYPES}
    assert counts["relationships"] == {rel: 1 for rel in RELATIONSHIP_TYPES}


def test_list_decisions_shape(reader, driver):
    items = reader.list_decisions(limit=10, decision="ESCALATE", source="hr.pdf")
    assert driver.queries[-1].params == {
        "request_id": None, "decision": "ESCALATE", "source": "hr.pdf", "limit": 10,
    }
    item = items[0]
    for key in ("request_id", "decision", "created_at", "query_preview", "topic",
                "answerability_score", "claim_count", "evidence_count",
                "document_count", "reason_codes"):
        assert key in item
    assert item["reason_codes"] == ["CONTRADICTION"]


def test_decision_subgraph_shape_and_filtering(reader):
    subgraph = reader.decision_subgraph("r1")
    assert subgraph["decision"]["request_id"] == "r1"

    types = {n["id"]: n["type"] for n in subgraph["nodes"]}
    assert "s1" not in types, "a node with a foreign label is dropped"
    assert set(types.values()) == set(NODE_TYPES)
    for node in subgraph["nodes"]:
        assert set(node) == {"id", "type", "label", "props"}

    edge_types = {e["type"] for e in subgraph["edges"]}
    assert edge_types == {"HAS_CLAIM", "CONFLICTS_WITH", "SUPERSEDES"}
    for edge in subgraph["edges"]:
        assert set(edge) == {"id", "type", "from", "to", "props"}
    conflict = next(e for e in subgraph["edges"] if e["type"] == "CONFLICTS_WITH")
    assert conflict["id"] == "r1:evidence:0|CONFLICTS_WITH|r1:evidence:0|numeric"
    supersedes = next(e for e in subgraph["edges"] if e["type"] == "SUPERSEDES")
    assert supersedes["id"] == "doc:hr.pdf@v2|SUPERSEDES|doc:hr.pdf@v1|"


def test_a_missing_decision_is_none(reader):
    assert reader.decision_subgraph("absent") is None


def test_documents_shape(reader):
    item = reader.list_documents()[0]
    assert item["doc_id"] == "doc:hr.pdf@v1"
    assert item["conflict_count"] == 0
    assert item["superseded_by"] == ["doc:hr.pdf@v2"]
    assert item["supersedes"] == []


def test_neighbors_shape_and_filtering(reader):
    subgraph = reader.neighbors("doc:hr.pdf@v1")
    assert subgraph["center"] == "doc:hr.pdf@v1"
    assert [n["id"] for n in subgraph["nodes"]] == ["doc:hr.pdf@v1", "r1:evidence:0"]
    assert [e["type"] for e in subgraph["edges"]] == ["FROM"]
    assert reader.neighbors("absent") is None


def test_display_labels():
    assert display_label("Decision", {"decision": "ESCALATE", "answerability_score": 0.41}) == "ESCALATE · 0.41"
    assert display_label("Decision", {"decision": "ABSTAIN"}) == "ABSTAIN"
    assert display_label("Document", {"source": "hr.pdf", "version": "v2"}) == "hr.pdf@v2"
    assert display_label("Document", {"source": "hr.pdf"}) == "hr.pdf"
    assert display_label("Reason", {"code": "STALE_EVIDENCE"}) == "STALE_EVIDENCE"
    assert display_label("Evidence", {"source": "hr.pdf", "evidence_index": 1}) == "hr.pdf#1"
    long_claim = display_label("Claim", {"text": "word " * 100})
    assert len(long_claim) <= 60 and long_claim.endswith("…")


def test_non_json_values_become_strings():
    class Temporal:
        def __str__(self):
            return "2026-11-17"

    node = make_node(["Document"], {"id": "doc:x", "source": "x", "date": Temporal(), "version_key": (1, 2)})
    assert node["props"]["date"] == "2026-11-17"
    assert node["props"]["version_key"] == [1, 2]


def test_malformed_nodes_and_edges_are_dropped():
    assert make_node(["Unknown"], {"id": "x"}) is None
    assert make_node(["Claim"], {"text": "no id"}) is None
    assert make_node(["Claim"], None) is None
    assert make_edge({"type": "OWNS", "from": "a", "to": "b"}) is None
    assert make_edge({"type": "FROM", "from": "a", "to": None}) is None
    assert make_edge(None) is None
