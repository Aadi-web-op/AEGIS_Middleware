"""Cross-decision intelligence against a real Neo4j.

Skipped unless `NEO4J_URI` is set (e.g. `bolt://localhost:7687`; user and
password from `NEO4J_USER` / `NEO4J_PASSWORD`, default neo4j/password).

Writes a handful of traces through the real `Neo4jGraphSink` + `build_trace`,
all under a per-run request_id prefix `itest-<uuid>-` (document sources carry
the same marker), runs the service scoped to that prefix, and deletes only
nodes whose id/request_id contains the marker. Seed data is never touched.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List

import pytest

from app.graph.neo4j_sink import Neo4jGraphSink
from app.graph.trace_builder import build_trace
from app.intelligence.audit import AuditReader
from app.intelligence.queries import QUERIES
from app.intelligence.service import IntelligenceService

CLEANUP_CYPHER = (
    "MATCH (n) WHERE (n.id IS NOT NULL AND n.id CONTAINS $marker) "
    "OR (n.request_id IS NOT NULL AND n.request_id CONTAINS $marker) "
    "DETACH DELETE n"
)
COUNT_CYPHER = (
    "MATCH (n) WHERE (n.id IS NOT NULL AND n.id CONTAINS $marker) "
    "OR (n.request_id IS NOT NULL AND n.request_id CONTAINS $marker) "
    "RETURN count(n) AS n"
)


def build_scenario(marker: str) -> List[Dict[str, Any]]:
    """Traces for: a numeric conflict in 3 decisions, a knowledge gap in 2,
    and a superseded version relied on in 2 decisions after the newer one."""
    prefix = f"{marker}-"
    travel = {"text": "Meal allowance is $75 per day.", "source": f"{marker}-travel.pdf",
              "version": "3", "date": "2025-06-01"}
    circular = {"text": "Meal allowance is capped at $50 per day.",
                "source": f"{marker}-circular.pdf", "version": "1", "date": "2026-04-01"}
    leave_v1 = {"text": "Employees get 20 days of annual leave.", "source": f"{marker}-leave.pdf",
                "version": "1", "date": "2025-01-10"}
    leave_v2 = {"text": "Employees get 25 days of annual leave.", "source": f"{marker}-leave.pdf",
                "version": "2", "date": "2026-03-01"}

    traces = []
    for i, decision in enumerate(("ESCALATE", "CAVEAT", "ESCALATE")):
        traces.append(build_trace(
            request_id=f"{prefix}meal-{i}", decision=decision,
            query="What is the daily meal allowance?",
            created_at=f"2026-05-0{i + 1}T10:00:00+00:00",
            evidence=[travel, circular],
            entailment_details={"claims": [{
                "claim_index": 0, "claim": "The meal allowance is $75 per day.",
                "status": "CONTRADICTED", "support": 0.1,
                "supporting_evidence_indices": [0], "contradicting_evidence_indices": [1]}]},
            contradiction_details={"conflicts": [{
                "graph_edge_eligible": True, "index_a": 0, "index_b": 1, "kind": "numeric",
                "value_a": "75", "value_b": "50", "reason": "different amounts"}]},
            reasons=[{"code": "CONTRADICTION", "message": "Sources disagree on the amount."}],
        ))
    for i in range(2):
        traces.append(build_trace(
            request_id=f"{prefix}gap-{i}", decision="ABSTAIN",
            query="How does contractor equity vesting work?",
            created_at=f"2026-05-1{i}T10:00:00+00:00",
            evidence=[], reasons=[{"code": "LOW_EVIDENCE", "message": "Nothing relevant."}],
        ))
    for i in range(2):
        traces.append(build_trace(
            request_id=f"{prefix}leave-{i}", decision="ANSWER",
            query="How many days of annual leave do I get?",
            created_at=f"2026-05-2{i}T10:00:00+00:00",
            evidence=[leave_v1],
            entailment_details={"claims": [{
                "claim_index": 0, "claim": "You get 20 days of annual leave.",
                "status": "SUPPORTED", "support": 0.9,
                "supporting_evidence_indices": [0], "contradicting_evidence_indices": []}]},
        ))
    # One decision that saw the newer version, so it exists in the graph.
    traces.append(build_trace(
        request_id=f"{prefix}leave-new", decision="ANSWER",
        query="Annual leave days in 2026?", created_at="2026-04-01T10:00:00+00:00",
        evidence=[leave_v2],
        entailment_details={"claims": [{
            "claim_index": 0, "claim": "You get 25 days.", "status": "SUPPORTED",
            "support": 0.9, "supporting_evidence_indices": [0],
            "contradicting_evidence_indices": []}]},
    ))
    return traces


def test_scenario_traces_are_accepted_by_the_sink():
    """Offline guard for the live test's data: the real sink builds Cypher for it."""
    sink = Neo4jGraphSink(driver=object())
    for trace in build_scenario("itest-offline"):
        assert sink.build_statements(trace)


@pytest.mark.skipif(not os.environ.get("NEO4J_URI"), reason="NEO4J_URI is not set")
def test_findings_from_real_graph(tmp_path):
    from app.graph.driver import make_driver

    driver = make_driver(
        os.environ["NEO4J_URI"],
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "password"),
    )
    marker = f"itest-{uuid.uuid4().hex[:12]}"
    prefix = f"{marker}-"
    try:
        sink = Neo4jGraphSink(driver)
        traces = build_scenario(marker)
        for trace in traces:
            assert sink.write_trace(trace), sink.last_error

        svc = IntelligenceService(driver=driver, audit=AuditReader(db_path=str(tmp_path / "a.db")))
        out = svc.summary(prefix)
        assert out["graph"] == {"available": True}, out["graph"]
        assert out["data"]["graph_decisions"] == len(traces)
        assert out["data"]["sufficient"] is True

        kinds = {f["kind"] for f in out["findings"]}
        assert {"contradiction_hotspot", "knowledge_gap", "stale_version_in_use",
                "unsupported_source", "escalation_root_cause"} <= kinds, kinds
        for f in out["findings"]:
            assert len(f["request_ids"]) >= 2
            assert all(rid.startswith(prefix) for rid in f["request_ids"]), f
            assert all(part in QUERIES for part in f["query"].split("+"))

        hotspot = next(f for f in out["findings"] if f["kind"] == "contradiction_hotspot")
        assert hotspot["request_ids"] == [f"{prefix}meal-{i}" for i in range(3)]
        stale = next(f for f in out["findings"] if f["kind"] == "stale_version_in_use")
        assert stale["subjects"][0]["id"] == f"doc:{marker}-leave.pdf@1"
        assert stale["request_ids"] == [f"{prefix}leave-0", f"{prefix}leave-1"]
        # The all-ESCALATE "meal" topic is a legitimate gap too, so look up the
        # finding for the ABSTAIN-only topic rather than assuming ranking order.
        gaps = [f["request_ids"] for f in out["findings"] if f["kind"] == "knowledge_gap"]
        assert [f"{prefix}gap-0", f"{prefix}gap-1"] in gaps, gaps

        radius = svc.blast_radius(f"doc:{marker}-leave.pdf@1", prefix)
        assert radius["relied_on"]["count"] == 2
        docs = svc.documents(prefix)["items"]
        assert docs and all(marker in d["doc_id"] for d in docs)
    finally:
        with driver.session() as session:
            session.run(CLEANUP_CYPHER, marker=marker).consume()
            left = session.run(COUNT_CYPHER, marker=marker).single()["n"]
        driver.close()
        assert left == 0
