"""Integration tests against a real Neo4j.

Skipped unless `NEO4J_URI` is set (e.g. `bolt://localhost:7687`).

Isolation: every node these tests create has an id that contains a
per-run marker -- request ids are `itest-<uuid>-...`, document sources are
`itest-<uuid>-....pdf` -- and cleanup deletes only nodes whose id contains
that marker. Seed data and anything else in the database is never touched.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("NEO4J_URI"), reason="NEO4J_URI is not set"
)

from app.graph.async_sink import AsyncGraphSink  # noqa: E402
from app.graph.contract import NODE_TYPES  # noqa: E402
from app.graph.neo4j_sink import Neo4jGraphSink  # noqa: E402
from app.graph.reader import GraphReader  # noqa: E402
from app.graph.schema import apply_schema  # noqa: E402
from app.graph.trace_builder import build_trace  # noqa: E402

CLEANUP_CYPHER = (
    "MATCH (n) WHERE (n.id IS NOT NULL AND n.id CONTAINS $marker) "
    "OR (n.request_id IS NOT NULL AND n.request_id CONTAINS $marker) "
    "DETACH DELETE n"
)
OWN_NODES_CYPHER = (
    "MATCH (n) WHERE (n.id IS NOT NULL AND n.id CONTAINS $marker) "
    "OR (n.request_id IS NOT NULL AND n.request_id CONTAINS $marker) "
    "RETURN count(n) AS nodes"
)
OWN_RELS_CYPHER = (
    "MATCH (a)-[r]->(b) WHERE a.id CONTAINS $marker OR b.id CONTAINS $marker "
    "RETURN count(r) AS rels"
)
DUPLICATES_CYPHER = (
    "MATCH (n) WHERE n.id CONTAINS $marker "
    "WITH labels(n)[0] AS label, n.id AS id, count(*) AS copies "
    "WHERE copies > 1 RETURN label, id, copies"
)
DUPLICATE_RELS_CYPHER = (
    "MATCH (a)-[r]->(b) WHERE a.id CONTAINS $marker "
    "WITH a.id AS start, type(r) AS type, b.id AS end, r.kind AS kind, count(*) AS copies "
    "WHERE copies > 1 RETURN start, type, end, kind, copies"
)


@pytest.fixture(scope="module")
def driver():
    from app.graph.driver import make_driver

    drv = make_driver(
        os.environ["NEO4J_URI"],
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "password"),
    )
    try:
        drv.verify_connectivity()
    except Exception as exc:  # pragma: no cover - environment dependent
        drv.close()
        pytest.skip(f"Neo4j at {os.environ['NEO4J_URI']} is not reachable: {exc}")
    apply_schema(drv)
    yield drv
    drv.close()


@pytest.fixture
def marker(driver):
    value = f"itest-{uuid.uuid4().hex[:12]}"
    yield value
    with driver.session() as session:
        session.run(CLEANUP_CYPHER, marker=value).consume()


def _query(driver, cypher, **params):
    with driver.session() as session:
        return session.run(cypher, **params).data()


def _own_counts(driver, marker):
    return (
        _query(driver, OWN_NODES_CYPHER, marker=marker)[0]["nodes"],
        _query(driver, OWN_RELS_CYPHER, marker=marker)[0]["rels"],
    )


def _trace(marker, suffix, version, date, decision="CAVEAT", created_at="2026-11-17T10:00:00.000+00:00"):
    source = f"{marker}-leave.pdf"
    return build_trace(
        request_id=f"{marker}-{suffix}",
        decision=decision,
        headline="integration test",
        evidence=[
            {"text": f"Leave allowance per version {version}.", "source": source,
             "version": version, "date": date},
            {"text": "An uncited handbook passage.", "source": f"{marker}-handbook.pdf",
             "version": "v1", "date": "2020-01-01"},
        ],
        entailment_details={
            "claims": [
                {"claim_index": 0, "claim": "Employees get leave.", "status": "SUPPORTED",
                 "support": 0.9, "supporting_evidence_indices": [0],
                 "contradicting_evidence_indices": []}
            ]
        },
        reasons=[{"code": "STALE_EVIDENCE", "message": "integration test reason"}],
        answerability_score=0.55,
        policy_version="itest",
        profile="standard",
        query="How many annual leave days do I get?",
        created_at=created_at,
        degraded=False,
    )


def test_writing_the_same_trace_twice_creates_no_duplicates(driver, marker):
    sink = Neo4jGraphSink(driver)
    trace = _trace(marker, "a", "v1", "2023-01-01")

    assert sink.write_trace(trace) is True, sink.last_error
    first = _own_counts(driver, marker)
    assert sink.write_trace(trace) is True, sink.last_error
    assert sink.write_trace(trace) is True, sink.last_error
    again = _own_counts(driver, marker)

    assert first == again
    assert first[0] == len(trace["nodes"])
    assert first[1] == len(trace["edges"])
    assert _query(driver, DUPLICATES_CYPHER, marker=marker) == []
    assert _query(driver, DUPLICATE_RELS_CYPHER, marker=marker) == []


def test_created_at_is_first_write_wins(driver, marker):
    sink = Neo4jGraphSink(driver)
    sink.write_trace(_trace(marker, "a", "v1", "2023-01-01"))
    sink.write_trace(_trace(marker, "a", "v1", "2023-01-01", created_at="2031-01-01T00:00:00+00:00"))
    rows = _query(
        driver,
        "MATCH (d:Decision {request_id: $rid}) RETURN d.created_at AS created_at, "
        "d.topic AS topic, d.query_preview AS preview, d.trace_version AS v, d.degraded AS degraded",
        rid=f"{marker}-a",
    )
    assert rows == [
        {
            "created_at": "2026-11-17T10:00:00.000+00:00",
            "topic": "annual|day|leave",
            "preview": "How many annual leave days do I get?",
            "v": "2",
            "degraded": False,
        }
    ]


def test_supersedes_is_derived_across_two_separate_evaluations(driver, marker):
    sink = Neo4jGraphSink(driver)
    supersedes = (
        "MATCH (a:Document)-[r:SUPERSEDES]->(b:Document) WHERE a.id CONTAINS $marker "
        "RETURN a.version AS newer, b.version AS older, r.derived AS derived"
    )

    # Evaluation 1 only ever saw v1: nothing to order yet.
    assert sink.write_trace(_trace(marker, "old", "v1", "2023-01-01")) is True, sink.last_error
    assert _query(driver, supersedes, marker=marker) == []

    # Evaluation 2, a different request, saw only v2.
    assert sink.write_trace(_trace(marker, "new", "v2", "2024-01-01")) is True, sink.last_error
    assert _query(driver, supersedes, marker=marker) == [
        {"newer": "v2", "older": "v1", "derived": "same_source_order"}
    ]

    # Replays and a third, older-than-both evaluation stay consistent.
    sink.write_trace(_trace(marker, "new", "v2", "2024-01-01"))
    sink.write_trace(_trace(marker, "older", "v0", "2022-01-01"))
    pairs = {(r["newer"], r["older"]) for r in _query(driver, supersedes, marker=marker)}
    assert pairs == {("v2", "v1"), ("v2", "v0"), ("v1", "v0")}
    assert _query(driver, DUPLICATE_RELS_CYPHER, marker=marker) == []


def test_version_numbers_order_documents_when_dates_are_missing(driver, marker):
    sink = Neo4jGraphSink(driver)
    sink.write_trace(_trace(marker, "p", "2024.2", None))
    sink.write_trace(_trace(marker, "q", "2024.10", None))
    sink.write_trace(_trace(marker, "r", "draft", None))  # not comparable: no edge
    rows = _query(
        driver,
        "MATCH (a:Document)-[:SUPERSEDES]->(b:Document) WHERE a.id CONTAINS $marker "
        "RETURN a.version AS newer, b.version AS older",
        marker=marker,
    )
    assert rows == [{"newer": "2024.10", "older": "2024.2"}]


def test_decision_subgraph_round_trips_through_the_reader(driver, marker):
    sink = Neo4jGraphSink(driver)
    sink.write_trace(_trace(marker, "old", "v1", "2023-01-01"))
    trace = _trace(marker, "new", "v2", "2024-01-01", decision="ESCALATE")
    assert sink.write_trace(trace) is True, sink.last_error

    reader = GraphReader(driver)
    subgraph = reader.decision_subgraph(trace["request_id"])

    assert {n["id"] for n in subgraph["nodes"]} == {n["id"] for n in trace["nodes"]}
    assert {(e["from"], e["type"], e["to"]) for e in subgraph["edges"]} == {
        (e["from"], e["type"], e["to"]) for e in trace["edges"]
    }
    assert {n["type"] for n in subgraph["nodes"]} == set(NODE_TYPES)
    assert {"RETRIEVED", "HAS_CLAIM", "SUPPORTED_BY", "FROM", "BECAUSE"} <= {
        e["type"] for e in subgraph["edges"]
    }
    summary = subgraph["decision"]
    assert summary["decision"] == "ESCALATE"
    assert summary["claim_count"] == 1
    assert summary["evidence_count"] == 2
    assert summary["document_count"] == 2
    assert summary["reason_codes"] == ["STALE_EVIDENCE"]
    assert summary["topic"] == "annual|day|leave"

    assert reader.decision_subgraph(f"{marker}-absent") is None

    # list filter by source finds both evaluations, newest first is stable.
    listed = reader.list_decisions(limit=50, source=f"{marker}-leave.pdf")
    assert {d["request_id"] for d in listed} == {f"{marker}-old", f"{marker}-new"}
    assert reader.list_decisions(limit=50, source=f"{marker}-leave.pdf", decision="ESCALATE")[0][
        "request_id"
    ] == f"{marker}-new"

    # documents: the old version is reported as superseded.
    documents = {d["doc_id"]: d for d in reader.list_documents(limit=500)}
    old_doc = documents[f"doc:{marker}-leave.pdf@v1"]
    assert old_doc["superseded_by"] == [f"doc:{marker}-leave.pdf@v2"]
    assert old_doc["decision_count"] == 1 and old_doc["supported_claim_count"] == 1
    assert documents[f"doc:{marker}-handbook.pdf@v1"]["decision_count"] == 2

    # neighbours of the shared handbook document: one evidence per decision.
    neighbors = reader.neighbors(f"doc:{marker}-handbook.pdf@v1")
    assert neighbors["center"] == f"doc:{marker}-handbook.pdf@v1"
    assert len([e for e in neighbors["edges"] if e["type"] == "FROM"]) == 2
    assert reader.neighbors(f"{marker}-absent") is None

    counts = reader.counts()
    assert counts["counts"]["Decision"] >= 2
    assert counts["relationships"]["RETRIEVED"] >= 4


def test_async_writer_and_routes_against_the_live_database(driver, marker):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.graph.routes import router

    class _NoClose(Neo4jGraphSink):
        def close(self):  # the module-scoped driver outlives this test
            pass

    writer = AsyncGraphSink(_NoClose(driver), register_atexit=False)
    trace = _trace(marker, "async", "v3", "2025-01-01")
    try:
        assert writer.write_trace(trace) is True
        assert writer.flush(timeout=30) is True
        stats = writer.stats()
        assert stats["written"] == 1 and stats["failed"] == 0, stats

        app = FastAPI()
        app.state.neo4j_driver = driver
        app.state.evaluator = type("E", (), {"graph_sink": writer})()
        app.include_router(router)
        client = TestClient(app)

        status = client.get("/v1/graph/status").json()
        assert status["configured"] is True and status["connected"] is True
        assert status["writer"]["written"] == 1

        response = client.get(f"/v1/graph/decisions/{trace['request_id']}")
        assert response.status_code == 200
        assert len(response.json()["nodes"]) == len(trace["nodes"])

        assert client.get(f"/v1/graph/decisions/{marker}-absent").status_code == 404
        assert client.get("/v1/graph/decisions?limit=5").status_code == 200
        assert client.get("/v1/graph/documents?limit=5").status_code == 200
        neighbors = client.get(f"/v1/graph/nodes/{trace['request_id']}/neighbors")
        assert neighbors.status_code == 200
        assert neighbors.json()["center"] == trace["request_id"]
    finally:
        writer.close(timeout=5)


def test_cleanup_removes_only_this_runs_nodes(driver):
    before = _query(driver, "MATCH (n) RETURN count(n) AS n")[0]["n"]
    marker = f"itest-{uuid.uuid4().hex[:12]}"
    Neo4jGraphSink(driver).write_trace(_trace(marker, "tmp", "v1", "2023-01-01"))
    assert _own_counts(driver, marker)[0] > 0
    with driver.session() as session:
        session.run(CLEANUP_CYPHER, marker=marker).consume()
    assert _own_counts(driver, marker) == (0, 0)
    assert _query(driver, "MATCH (n) RETURN count(n) AS n")[0]["n"] == before
