"""Trace v2: Decision context, RETRIEVED, same-source SUPERSEDES, and how
the writer stores them (fake driver -- no Neo4j server involved)."""

from __future__ import annotations

from app.core.evaluator import Evaluator
from app.evidence.stubs import FixedSignal
from app.graph.contract import (
    QUERY_PREVIEW_CHARS,
    RELATIONSHIP_TYPES,
    TRACE_VERSION,
    validate_trace,
)
from app.graph.neo4j_sink import LINK_SUPERSEDES_CYPHER, Neo4jGraphSink
from app.graph.topics import topic_key
from app.graph.trace_builder import build_trace, document_sort_keys
from app.schemas import EvaluateRequest
from tests.graph.fake_driver import FakeDriver, FakeGraph

SECRET = "gsk_abcdefghijklmnopqrstuvwxyz0123456789"

EVIDENCE = [
    {"text": "18 days.", "source": "leave.pdf", "version": "v1", "date": "2023-01-01"},
    {"text": "24 days.", "source": "leave.pdf", "version": "v2", "date": "2024-01-01"},
    {"text": "Unrelated.", "source": "handbook.pdf", "version": "v9", "date": "2020-01-01"},
]


def _edges(trace, relationship):
    return [e for e in trace["edges"] if e["type"] == relationship]


def _decision(trace):
    return next(n for n in trace["nodes"] if n["type"] == "Decision")


def _trace(**overrides):
    kwargs = dict(
        request_id="r-v2",
        decision="CAVEAT",
        evidence=EVIDENCE,
        query="How many annual leave days do I get?",
        created_at="2026-11-17T10:00:00.000+00:00",
        degraded=False,
    )
    kwargs.update(overrides)
    return build_trace(**kwargs)


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------
def test_retrieved_is_in_the_closed_vocabulary():
    assert "RETRIEVED" in RELATIONSHIP_TYPES
    assert TRACE_VERSION == "2"


# ---------------------------------------------------------------------------
# Decision context
# ---------------------------------------------------------------------------
def test_decision_carries_the_v2_context():
    trace = _trace()
    decision = _decision(trace)
    assert decision["created_at"] == "2026-11-17T10:00:00.000+00:00"
    assert decision["query_preview"] == "How many annual leave days do I get?"
    assert decision["topic"] == topic_key("How many annual leave days do I get?")
    assert decision["topic"] == "annual|day|leave"
    assert decision["degraded"] is False
    assert decision["trace_version"] == "2"
    assert trace["trace_version"] == "2"
    assert validate_trace(trace)["trace_version"] == "2"


def test_query_preview_is_redacted_and_capped():
    query = f"My key is {SECRET} -- " + "what is the leave policy? " * 20
    decision = _decision(_trace(query=query))
    assert SECRET not in decision["query_preview"]
    assert "[REDACTED]" in decision["query_preview"]
    assert len(decision["query_preview"]) <= QUERY_PREVIEW_CHARS


def test_the_full_query_never_appears_in_the_trace():
    query = "leave " + "x" * 400 + " TAILMARKER"
    trace = _trace(query=query)
    assert "TAILMARKER" not in repr(trace)


def test_a_keywordless_query_stores_no_topic():
    decision = _decision(_trace(query="What is it?"))
    assert "topic" not in decision
    assert decision["query_preview"] == "What is it?"


def test_context_is_optional_for_old_callers():
    decision = _decision(build_trace(request_id="r", decision="ANSWER"))
    for key in ("created_at", "query_preview", "topic", "degraded"):
        assert key not in decision


# ---------------------------------------------------------------------------
# RETRIEVED
# ---------------------------------------------------------------------------
def test_every_evidence_passage_is_retrieved_cited_or_not():
    trace = _trace()
    retrieved = _edges(trace, "RETRIEVED")
    assert [e["to"] for e in retrieved] == [f"r-v2:evidence:{i}" for i in range(3)]
    assert all(e["from"] == "r-v2" for e in retrieved)
    assert [e["evidence_index"] for e in retrieved] == [0, 1, 2]
    # No claim cited anything here, so RETRIEVED is the only path to them.
    assert _edges(trace, "SUPPORTED_BY") == []


def test_no_evidence_means_no_retrieved_edges():
    assert _edges(_trace(evidence=[]), "RETRIEVED") == []


# ---------------------------------------------------------------------------
# SUPERSEDES within a trace
# ---------------------------------------------------------------------------
def test_same_source_versions_supersede_without_a_reported_conflict():
    edges = _edges(_trace(), "SUPERSEDES")
    assert len(edges) == 1
    assert edges[0]["from"] == "doc:leave.pdf@v2"
    assert edges[0]["to"] == "doc:leave.pdf@v1"
    assert edges[0]["derived"] == "same_source_order"


def test_different_sources_are_never_ordered_by_the_same_source_rule():
    evidence = [
        {"text": "a", "source": "a.pdf", "version": "v1", "date": "2023-01-01"},
        {"text": "b", "source": "b.pdf", "version": "v2", "date": "2024-01-01"},
    ]
    assert _edges(_trace(evidence=evidence), "SUPERSEDES") == []


def test_incomparable_same_source_versions_get_no_edge():
    evidence = [
        {"text": "a", "source": "p.pdf", "version": "draft"},
        {"text": "b", "source": "p.pdf", "version": "final"},
    ]
    assert _edges(_trace(evidence=evidence), "SUPERSEDES") == []


def test_a_version_conflict_and_the_same_source_rule_yield_one_edge():
    trace = _trace(
        contradiction_details={
            "conflicts": [
                {"kind": "version", "index_a": 0, "index_b": 1, "graph_edge_eligible": True}
            ]
        }
    )
    edges = _edges(trace, "SUPERSEDES")
    assert len(edges) == 1
    assert edges[0]["derived"] == "version_conflict"


def test_documents_carry_sort_keys():
    docs = {n["id"]: n for n in _trace()["nodes"] if n["type"] == "Document"}
    assert docs["doc:leave.pdf@v2"]["date_key"] == "2024-01-01"
    assert docs["doc:leave.pdf@v2"]["version_key"] == [2]
    assert document_sort_keys({"version": "2024.2"}) == {"version_key": [2024, 2]}
    assert document_sort_keys({"version": "draft", "date": "not a date"}) == {}


# ---------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------
def test_created_at_is_first_write_wins():
    driver = FakeDriver()
    sink = Neo4jGraphSink(driver)
    sink.write_trace(_trace())
    sink.write_trace(_trace(created_at="2030-01-01T00:00:00+00:00"))

    for call in driver.node_merges("Decision"):
        assert "created_at" not in call.params["props"]
        assert "SET n.created_at = coalesce(n.created_at, $created_at)" in call.cypher

    graph = FakeGraph.from_driver(driver)
    assert graph.labels("Decision")[0]["created_at"] == "2026-11-17T10:00:00.000+00:00"


def test_writing_twice_duplicates_nothing_including_retrieved():
    driver = FakeDriver()
    sink = Neo4jGraphSink(driver)
    sink.write_trace(_trace())
    first = FakeGraph.from_driver(driver)
    sink.write_trace(_trace())
    second = FakeGraph.from_driver(driver)

    assert second.nodes == first.nodes
    assert second.edges == first.edges
    assert len(second.relationships("RETRIEVED")) == 3
    assert len(second.relationships("SUPERSEDES")) == 1


def test_writer_caps_and_redacts_a_query_preview_it_is_handed():
    driver = FakeDriver()
    trace = {
        "request_id": "r-raw",
        "decision": "ANSWER",
        "nodes": [
            {
                "id": "r-raw",
                "type": "Decision",
                "query_preview": f"{SECRET} " + "q" * 500,
            },
            {"id": "e0", "type": "Evidence", "preview": "p" * 500},
        ],
        "edges": [],
    }
    assert Neo4jGraphSink(driver).write_trace(trace) is True
    stored = driver.node_props("Decision")[0]["query_preview"]
    assert len(stored) <= QUERY_PREVIEW_CHARS
    assert SECRET not in stored
    assert len(driver.node_props("Evidence")[0]["preview"]) == 120


def test_linking_statement_is_parameterised_and_scoped_to_trace_sources():
    driver = FakeDriver()
    Neo4jGraphSink(driver).write_trace(_trace())

    links = [c for c in driver.calls if c.cypher == LINK_SUPERSEDES_CYPHER]
    assert len(links) == 1
    assert links[0].params == {
        "sources": ["handbook.pdf", "leave.pdf"],
        "derived": "same_source_order",
    }
    assert driver.calls[-1] is links[0], "linking runs after the trace's own MERGEs"
    assert driver.transactions == 1, "and inside the same transaction"
    # Nothing from the trace is spliced into the statement.
    assert "leave.pdf" not in LINK_SUPERSEDES_CYPHER
    assert "UNWIND $sources" in LINK_SUPERSEDES_CYPHER
    assert "MERGE (a)-[s:SUPERSEDES]->(b)" in LINK_SUPERSEDES_CYPHER
    assert "CREATE" not in LINK_SUPERSEDES_CYPHER and "DELETE" not in LINK_SUPERSEDES_CYPHER


def test_a_hostile_source_name_stays_a_parameter():
    hostile = "x'}) DETACH DELETE n //"
    driver = FakeDriver()
    evidence = [{"text": "a", "source": hostile, "version": "v1"}]
    assert Neo4jGraphSink(driver).write_trace(_trace(evidence=evidence)) is True
    for call in driver.calls:
        assert hostile not in call.cypher
        assert "DETACH" not in call.cypher


def test_no_documents_means_no_linking_statement():
    driver = FakeDriver()
    Neo4jGraphSink(driver).write_trace(_trace(evidence=[]))
    assert all(c.cypher != LINK_SUPERSEDES_CYPHER for c in driver.calls)


def test_linking_can_be_switched_off():
    driver = FakeDriver()
    Neo4jGraphSink(driver, link_supersedes=False).write_trace(_trace())
    assert all(c.cypher != LINK_SUPERSEDES_CYPHER for c in driver.calls)


def test_a_document_without_a_date_does_not_erase_a_stored_one():
    driver = FakeDriver()
    evidence = [{"text": "a", "source": "p.pdf", "version": "v1"}]
    Neo4jGraphSink(driver).write_trace(_trace(evidence=evidence))
    props = driver.node_props("Document")[0]
    assert "date" not in props and "date_key" not in props


# ---------------------------------------------------------------------------
# evaluator wiring
# ---------------------------------------------------------------------------
class _Recording:
    def __init__(self):
        self.traces = []

    def write_trace(self, trace):
        self.traces.append(trace)
        return True


def _evaluator(sink):
    signals = [
        FixedSignal("relevance", 0.9),
        FixedSignal("entailment", 0.85),
        FixedSignal("contradiction", 0.05),
        FixedSignal("freshness", 0.95),
        FixedSignal("completeness", 0.9),
        FixedSignal("ambiguity", 0.05),
    ]
    return Evaluator(signals, graph_sink=sink)


def test_the_evaluator_passes_query_time_and_degraded_into_the_trace():
    sink = _Recording()
    request = EvaluateRequest(
        query="How many annual leave days do I get?",
        answer="You get 24 days.",
        evidence=[{"text": "Employees get 24 days.", "source": "leave.pdf", "version": "v2"}],
    )
    response = _evaluator(sink).evaluate(request)

    decision = _decision(sink.traces[0])
    assert decision["query_preview"] == request.query
    assert decision["topic"] == "annual|day|leave"
    assert decision["degraded"] is False
    assert decision["created_at"].startswith("20") and "T" in decision["created_at"]
    assert _edges(sink.traces[0], "RETRIEVED")
    assert response.trace["request_id"] == response.request_id


def test_the_no_evidence_path_also_carries_the_context():
    sink = _Recording()
    request = EvaluateRequest(query="What is the parking policy?", answer="Unknown.", evidence=[])
    _evaluator(sink).evaluate(request)

    decision = _decision(sink.traces[0])
    assert decision["decision"] == "ABSTAIN"
    assert decision["topic"] == "parking|policy"
    assert decision["created_at"]
    assert decision["degraded"] is False
