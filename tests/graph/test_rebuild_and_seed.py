"""Rebuildability: the graph can be replayed from the SQLite audit log, and
seeding is idempotent and leaves a matching audit row."""

from __future__ import annotations

import json
import sqlite3

from app.audit import AuditLogger
from app.graph.neo4j_sink import Neo4jGraphSink
from app.schemas import EvaluateRequest
from scripts.rebuild_graph import rebuild, trace_from_row
from scripts.seed_neo4j import case_request_id, evaluate_case, rekey_trace, seed_cases
from tests.benchmark.test_cases import DEV_CASES
from tests.graph.fake_driver import FakeDriver, FakeGraph
from tests.graph.test_trace_v2 import _evaluator


class _Capture:
    def __init__(self):
        self.traces = []

    def write_trace(self, trace):
        self.traces.append(trace)
        return True


def _request(query="How many annual leave days do I get?"):
    return EvaluateRequest(
        query=query,
        answer="You get 24 days.",
        evidence=[
            {"text": "Employees get 18 days.", "source": "leave.pdf", "version": "v1", "date": "2023-01-01"},
            {"text": "Employees get 24 days.", "source": "leave.pdf", "version": "v2", "date": "2024-01-01"},
        ],
    )


def _logged_db(tmp_path, n=2):
    """An audit DB holding `n` real evaluations, plus the live traces."""
    db = tmp_path / "audit.db"
    audit = AuditLogger(db)
    live = _Capture()
    evaluator = _evaluator(live)
    for i in range(n):
        request = _request(f"How many annual leave days do I get? #{i}")
        audit.log_evaluation(request, evaluator.evaluate(request))
    audit.log_generation_failure("a failed generation", "boom")  # no response_json
    return str(db), live.traces


# ---------------------------------------------------------------------------
# rebuild
# ---------------------------------------------------------------------------
def test_rebuild_reproduces_the_graph_the_live_writes_produced(tmp_path):
    db, live_traces = _logged_db(tmp_path)

    live_driver = FakeDriver()
    live_sink = Neo4jGraphSink(live_driver)
    for trace in live_traces:
        live_sink.write_trace(trace)

    rebuilt_driver = FakeDriver()
    summary = rebuild(Neo4jGraphSink(rebuilt_driver), db)

    assert summary == {
        "rows": 3, "replayed": 2, "skipped_no_trace": 1, "skipped_invalid": 0, "failed": 0,
    }
    live_graph = FakeGraph.from_driver(live_driver)
    rebuilt_graph = FakeGraph.from_driver(rebuilt_driver)
    assert rebuilt_graph.nodes == live_graph.nodes
    assert rebuilt_graph.edges == live_graph.edges
    assert len(rebuilt_graph.relationships("RETRIEVED")) == 4


def test_rebuild_is_idempotent(tmp_path):
    db, _ = _logged_db(tmp_path)
    driver = FakeDriver()
    sink = Neo4jGraphSink(driver)

    rebuild(sink, db)
    once = FakeGraph.from_driver(driver)
    rebuild(sink, db)
    twice = FakeGraph.from_driver(driver)

    assert twice.nodes == once.nodes and twice.edges == once.edges


def test_rebuild_dry_run_writes_nothing(tmp_path):
    db, _ = _logged_db(tmp_path)
    summary = rebuild(None, db, dry_run=True)
    assert summary["replayed"] == 2


def test_rebuild_counts_failed_writes(tmp_path):
    db, _ = _logged_db(tmp_path)
    summary = rebuild(Neo4jGraphSink(FakeDriver(fail_on_session=True)), db)
    assert summary["failed"] == 2 and summary["replayed"] == 0


def test_rebuild_tolerates_a_database_without_the_response_column(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE audit_logs (request_id TEXT PRIMARY KEY, timestamp TEXT, query TEXT)")
    conn.execute("INSERT INTO audit_logs VALUES ('old-1', '2026-01-01T00:00:00+00:00', 'q')")
    conn.commit()
    conn.close()

    summary = rebuild(Neo4jGraphSink(FakeDriver()), str(db))
    assert summary["rows"] == 1 and summary["skipped_no_trace"] == 1


def test_rebuild_skips_an_invalid_trace(tmp_path):
    db = tmp_path / "bad.db"
    AuditLogger(db)
    conn = sqlite3.connect(db)
    bad = {"trace": {"request_id": "x", "nodes": [{"id": "n", "type": "Malware"}], "edges": []}}
    conn.execute(
        "INSERT INTO audit_logs (request_id, timestamp, response_json) VALUES (?, ?, ?)",
        ("x", "2026-01-01T00:00:00+00:00", json.dumps(bad)),
    )
    conn.execute(
        "INSERT INTO audit_logs (request_id, timestamp, response_json) VALUES (?, ?, ?)",
        ("y", "2026-01-02T00:00:00+00:00", "{not json"),
    )
    conn.commit()
    conn.close()

    driver = FakeDriver()
    summary = rebuild(Neo4jGraphSink(driver), str(db))
    assert summary["skipped_invalid"] == 1 and summary["skipped_no_trace"] == 1
    assert driver.calls == []


def test_a_v1_trace_is_upgraded_from_the_rows_own_columns():
    v1 = {"request_id": "old", "decision": "ABSTAIN",
          "nodes": [{"id": "old", "type": "Decision", "decision": "ABSTAIN"}], "edges": []}
    row = {
        "request_id": "old",
        "timestamp": "2026-10-01T09:00:00+00:00",
        "query": "What is the parking policy?",
        "response_json": json.dumps({"degraded": True, "trace": v1}),
    }
    decision = trace_from_row(row)["nodes"][0]
    assert decision["created_at"] == "2026-10-01T09:00:00+00:00"
    assert decision["query_preview"] == "What is the parking policy?"
    assert decision["topic"] == "parking|policy"
    assert decision["degraded"] is True


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------
def test_rekey_rewrites_request_scoped_ids_only():
    trace = {
        "request_id": "abc",
        "nodes": [
            {"id": "abc", "type": "Decision", "request_id": "abc"},
            {"id": "abc:claim:0", "type": "Claim"},
            {"id": "doc:abc.pdf", "type": "Document"},
        ],
        "edges": [
            {"type": "HAS_CLAIM", "from": "abc", "to": "abc:claim:0"},
        ],
    }
    out = rekey_trace(trace, "bench-x")
    assert out["request_id"] == "bench-x"
    assert [n["id"] for n in out["nodes"]] == ["bench-x", "bench-x:claim:0", "doc:abc.pdf"]
    assert out["nodes"][0]["request_id"] == "bench-x"
    assert out["edges"][0] == {"type": "HAS_CLAIM", "from": "bench-x", "to": "bench-x:claim:0"}
    assert trace["request_id"] == "abc", "the input is not mutated"


def test_a_seeded_case_uses_the_evaluators_own_v2_trace():
    case = DEV_CASES[0]
    response = evaluate_case(_evaluator(None), case)
    assert response.request_id == case_request_id(case)
    trace = response.trace
    assert trace["request_id"] == case_request_id(case)
    decision = next(n for n in trace["nodes"] if n["type"] == "Decision")
    assert decision["id"] == case_request_id(case)
    assert decision["trace_version"] == "2"
    assert decision["query_preview"]
    assert decision["headline"]
    assert any(e["type"] == "RETRIEVED" for e in trace["edges"])
    for edge in trace["edges"]:
        for end in (edge["from"], edge["to"]):
            assert end.startswith(("bench-", "doc:"))


def test_reseeding_creates_no_duplicates():
    driver = FakeDriver()
    sink = Neo4jGraphSink(driver)
    evaluator = _evaluator(None)

    seed_cases(sink=sink, cases=DEV_CASES[:4], evaluator=evaluator)
    once = FakeGraph.from_driver(driver)
    seed_cases(sink=sink, cases=DEV_CASES[:4], evaluator=evaluator)
    twice = FakeGraph.from_driver(driver)

    assert len(twice.labels("Decision")) == 4
    assert set(twice.nodes) == set(once.nodes)
    assert set(twice.edges) == set(once.edges)
    # created_at is first-write-wins, so even the timestamps are unchanged.
    assert twice.nodes == once.nodes


def test_seeding_writes_a_matching_audit_row_and_is_rebuildable(tmp_path):
    db = tmp_path / "audit.db"
    audit = AuditLogger(db)
    seeded_driver = FakeDriver()

    summary = seed_cases(
        sink=Neo4jGraphSink(seeded_driver),
        cases=DEV_CASES[:3],
        evaluator=_evaluator(None),
        audit_logger=audit,
    )
    assert summary["successful_writes"] == 3 and summary["audit_records"] == 3

    for request_id in summary["seeded_request_ids"]:
        assert request_id.startswith("bench-")
        assert audit.get_record(request_id) is not None

    rebuilt_driver = FakeDriver()
    assert rebuild(Neo4jGraphSink(rebuilt_driver), str(db))["replayed"] == 3
    assert FakeGraph.from_driver(rebuilt_driver).nodes == FakeGraph.from_driver(seeded_driver).nodes
    assert FakeGraph.from_driver(rebuilt_driver).edges == FakeGraph.from_driver(seeded_driver).edges
