"""Neo4jGraphSink against a fake driver -- no Neo4j server involved.

Assertions are on the generated Cypher and its parameters, and on an
in-memory replay of the recorded MERGE statements (`FakeGraph`), which is
how idempotency is checked without a database.
"""

from __future__ import annotations

import logging

import pytest

from app.graph.contract import (
    CONFLICT_KINDS,
    EVIDENCE_PREVIEW_CHARS,
    RELATIONSHIP_TYPES,
    RETRIEVED_TEXT_KEYS,
    TraceContractError,
    validate_trace,
)
from app.graph.neo4j_sink import Neo4jGraphSink
from app.graph.sink import NullGraphSink, safe_write_trace
from tests.graph.conftest import REQUEST_ID
from tests.graph.fake_driver import FakeDriver, FakeGraph


@pytest.fixture
def driver():
    return FakeDriver()


@pytest.fixture
def sink(driver):
    return Neo4jGraphSink(driver, database="aegis")


# ---------------------------------------------------------------------------
# 1. a valid trace produces the expected operations
# ---------------------------------------------------------------------------
def test_valid_trace_writes_every_node_and_edge(sink, driver, trace):
    assert sink.write_trace(trace) is True

    assert len(driver.calls) == len(trace["nodes"]) + len(trace["edges"])
    assert driver.transactions == 1, "everything belongs to one write transaction"
    assert driver.sessions[0].database == "aegis"

    labels = sorted({call.label for call in driver.node_merges()})
    assert labels == ["Claim", "Decision", "Document", "Evidence", "Reason"]

    relationships = {call.relationship for call in driver.edge_merges()}
    assert relationships <= set(RELATIONSHIP_TYPES)
    assert {"HAS_CLAIM", "SUPPORTED_BY", "CONTRADICTED_BY", "FROM",
            "CONFLICTS_WITH", "SUPERSEDES", "BECAUSE", "ABOUT"} == relationships


def test_every_statement_is_a_merge_with_parameters_only(sink, driver, trace):
    sink.write_trace(trace)

    for call in driver.calls:
        assert "MERGE" in call.cypher
        # Values reach the database only as parameters.
        assert "$" in call.cypher
        for value in call.params.values():
            assert not isinstance(value, type(lambda: None))
        # Nothing from the trace's content is spliced into the query text.
        assert REQUEST_ID not in call.cypher
        assert "18" not in call.cypher


def test_decision_is_merged_on_request_id(sink, driver, trace):
    sink.write_trace(trace)

    decision = driver.node_merges("Decision")
    assert len(decision) == 1
    assert decision[0].cypher.startswith("MERGE (n:Decision {request_id: $merge_key})")
    assert decision[0].params["merge_key"] == REQUEST_ID
    assert decision[0].params["props"]["request_id"] == REQUEST_ID


# ---------------------------------------------------------------------------
# 2. repeating the same trace is idempotent
# ---------------------------------------------------------------------------
def test_repeating_a_trace_creates_no_duplicates(sink, driver, trace):
    assert sink.write_trace(trace) is True
    first = FakeGraph.from_driver(driver)

    assert sink.write_trace(trace) is True
    assert sink.write_trace(trace) is True
    third = FakeGraph.from_driver(driver)

    assert third.nodes == first.nodes
    assert third.edges == first.edges
    assert len(third.labels("Decision")) == 1
    assert driver.transactions == 3, "three writes really did happen"


def test_statements_are_deterministic(sink, trace):
    assert sink.build_statements(trace) == sink.build_statements(trace)


def test_a_repeated_benchmark_run_keeps_one_decision(driver, trace):
    """Rule: repeated benchmark runs must not create duplicate records."""
    sink = Neo4jGraphSink(driver)
    for _ in range(5):
        sink.write_trace(trace)

    graph = FakeGraph.from_driver(driver)
    assert len(graph.labels("Decision")) == 1
    assert len(graph.labels("Claim")) == 1
    assert len(graph.labels("Evidence")) == 3


def test_two_conflicts_between_one_pair_stay_two_edges(sink, driver, trace):
    """A numeric and a version conflict on the same pair must not collapse."""
    sink.write_trace(trace)
    sink.write_trace(trace)

    graph = FakeGraph.from_driver(driver)
    conflicts = graph.relationships("CONFLICTS_WITH")
    assert len(conflicts) == 2
    assert {kind for _, _, kind in conflicts} == {"numeric", "version"}

    for call in driver.edge_merges("CONFLICTS_WITH"):
        assert "MERGE (a)-[r:CONFLICTS_WITH {kind: $kind}]->(b)" in call.cypher
        assert call.params["kind"] in CONFLICT_KINDS


# ---------------------------------------------------------------------------
# 3. node properties map correctly
# ---------------------------------------------------------------------------
def test_decision_properties_map(sink, driver, trace):
    sink.write_trace(trace)
    props = driver.node_props("Decision")[0]
    assert props["decision"] == "ESCALATE"
    assert props["answerability_score"] == 0.41
    assert props["policy_version"] == "0.1.0"
    assert props["profile"] == "standard"
    assert props["headline"].startswith("Two versions")


def test_claim_properties_map(sink, driver, trace):
    sink.write_trace(trace)
    props = driver.node_props("Claim")[0]
    assert props["claim_index"] == 0
    assert props["text"] == "Employees receive 18 casual leaves."
    assert props["status"] == "SUPPORTED"
    assert props["support"] == 0.91
    assert props["nli_available"] is True


def test_evidence_properties_map(sink, driver, trace):
    sink.write_trace(trace)
    by_index = {p["evidence_index"]: p for p in driver.node_props("Evidence")}
    assert set(by_index) == {0, 1, 2}
    assert by_index[0]["source"] == "hr-policy.pdf"
    assert by_index[0]["version"] == "2023.1"
    assert by_index[0]["date"] == "2023-04-01"
    assert by_index[0]["preview"].startswith("Full-time employees")


def test_document_and_reason_properties_map(sink, driver, trace):
    sink.write_trace(trace)

    documents = {p["source"]: p for p in driver.node_props("Document")}
    assert set(documents) == {"hr-policy.pdf", "staff-handbook.pdf"}

    reasons = {p["code"]: p["message"] for p in driver.node_props("Reason")}
    assert reasons["CONTRADICTION"] == "Two policy passages disagree."
    assert reasons["UNSUPPORTED_CLAIM"] == "One claim is not fully supported."


# ---------------------------------------------------------------------------
# 4. supporting and contradicting edges use the right indices
# ---------------------------------------------------------------------------
def test_support_edges_point_at_the_right_evidence(sink, driver, trace):
    sink.write_trace(trace)

    supported = driver.edge_merges("SUPPORTED_BY")
    contradicted = driver.edge_merges("CONTRADICTED_BY")
    assert len(supported) == 1 and len(contradicted) == 1

    assert supported[0].params["to_id"] == f"{REQUEST_ID}:evidence:0"
    assert supported[0].params["props"]["evidence_index"] == 0
    assert contradicted[0].params["to_id"] == f"{REQUEST_ID}:evidence:1"
    assert contradicted[0].params["props"]["evidence_index"] == 1

    for call in supported + contradicted:
        assert call.params["from_id"] == f"{REQUEST_ID}:claim:0"
        assert call.cypher.startswith("MATCH (a:Claim {id: $from_id})")


def test_no_support_edge_is_invented_for_an_unimplicated_passage(sink, driver, trace):
    """Evidence 2 was never implicated, so nothing points at it."""
    sink.write_trace(trace)
    targets = {
        call.params["to_id"]
        for call in driver.edge_merges("SUPPORTED_BY")
        + driver.edge_merges("CONTRADICTED_BY")
    }
    assert f"{REQUEST_ID}:evidence:2" not in targets


# ---------------------------------------------------------------------------
# 5. conflict kind and values survive construction and storage
# ---------------------------------------------------------------------------
def test_conflict_kind_and_values_survive_to_cypher(sink, driver, trace):
    sink.write_trace(trace)

    by_kind = {
        call.params["kind"]: call.params["props"]
        for call in driver.edge_merges("CONFLICTS_WITH")
    }
    numeric = by_kind["numeric"]
    assert numeric["value_a"] == "18"
    assert numeric["value_b"] == "12"
    assert "18" in numeric["reason"] and "12" in numeric["reason"]
    assert numeric["severity"] == "high"

    version = by_kind["version"]
    assert version["value_a"] == "2023.1"
    assert version["value_b"] == "2024.2"


def test_conflict_edges_connect_the_detected_evidence_pair(sink, driver, trace):
    sink.write_trace(trace)
    for call in driver.edge_merges("CONFLICTS_WITH"):
        assert call.params["from_id"] == f"{REQUEST_ID}:evidence:0"
        assert call.params["to_id"] == f"{REQUEST_ID}:evidence:1"
        assert call.cypher.startswith("MATCH (a:Evidence {id: $from_id})")


# ---------------------------------------------------------------------------
# 6. document versions and supersession
# ---------------------------------------------------------------------------
def test_supersedes_points_from_the_newer_document(sink, driver, trace):
    sink.write_trace(trace)

    supersedes = driver.edge_merges("SUPERSEDES")
    assert len(supersedes) == 1
    assert supersedes[0].params["from_id"] == "doc:hr-policy.pdf@2024.2"
    assert supersedes[0].params["to_id"] == "doc:hr-policy.pdf@2023.1"
    assert supersedes[0].cypher.startswith("MATCH (a:Document {id: $from_id})")


def test_each_evidence_points_at_its_own_document(sink, driver, trace):
    sink.write_trace(trace)
    pairs = {
        (c.params["from_id"], c.params["to_id"]) for c in driver.edge_merges("FROM")
    }
    assert pairs == {
        (f"{REQUEST_ID}:evidence:0", "doc:hr-policy.pdf@2023.1"),
        (f"{REQUEST_ID}:evidence:1", "doc:hr-policy.pdf@2024.2"),
        (f"{REQUEST_ID}:evidence:2", "doc:staff-handbook.pdf@7"),
    }


# ---------------------------------------------------------------------------
# 7 & 8. previews are capped and full text is never stored
# ---------------------------------------------------------------------------
def test_every_stored_preview_is_within_the_cap(sink, driver, trace):
    sink.write_trace(trace)
    previews = [
        value
        for call in driver.calls
        for key, value in call.params["props"].items()
        if key == "preview" or key.endswith("_preview")
    ]
    assert previews, "the canonical trace does store previews"
    assert all(len(p) <= EVIDENCE_PREVIEW_CHARS for p in previews)


def test_a_long_passage_is_truncated_not_stored_whole(sink, driver, trace):
    sink.write_trace(trace)
    long_preview = next(
        p["preview"]
        for p in driver.node_props("Evidence")
        if p["evidence_index"] == 2
    )
    assert len(long_preview) == EVIDENCE_PREVIEW_CHARS
    assert "notice period expected" not in long_preview


def test_full_document_text_is_refused_even_if_a_trace_offers_it(driver):
    """Rule 7 holds regardless of what a future trace field is called."""
    sink = Neo4jGraphSink(driver)
    passage = "x" * 5000
    smuggled = {
        "request_id": "req-smuggle",
        "decision": "ANSWER",
        "nodes": [
            {"id": "req-smuggle", "type": "Decision"},
            {
                "id": "ev-0",
                "type": "Evidence",
                "preview": passage,
                "text": passage,
                "content": passage,
                "page_content": passage,
                "chunk_text": passage,
                "full_text": passage,
            },
            {"id": "doc:d", "type": "Document", "body": passage, "raw_text": passage},
        ],
        "edges": [{"type": "FROM", "from": "ev-0", "to": "doc:d"}],
        "reasons": [],
    }
    assert sink.write_trace(smuggled) is True

    for props in driver.node_props("Evidence") + driver.node_props("Document"):
        for key in RETRIEVED_TEXT_KEYS:
            assert key not in props, key
        assert all(
            not (isinstance(v, str) and len(v) > EVIDENCE_PREVIEW_CHARS)
            for v in props.values()
        )
    assert len(driver.node_props("Evidence")[0]["preview"]) == EVIDENCE_PREVIEW_CHARS


def test_claim_text_is_stored_but_bounded(driver):
    sink = Neo4jGraphSink(driver)
    sink.write_trace(
        {
            "request_id": "req-claim",
            "decision": "ANSWER",
            "nodes": [
                {"id": "req-claim", "type": "Decision"},
                {"id": "c0", "type": "Claim", "text": "y" * 1000},
            ],
            "edges": [{"type": "HAS_CLAIM", "from": "req-claim", "to": "c0"}],
        }
    )
    assert len(driver.node_props("Claim")[0]["text"]) == 300


# ---------------------------------------------------------------------------
# 9. malformed traces are handled safely
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad, because",
    [
        ({}, "no request_id"),
        ({"request_id": ""}, "empty request_id"),
        ({"request_id": 7}, "request_id is not a string"),
        ({"request_id": "r", "decision": "MAYBE"}, "unknown decision"),
        ({"request_id": "r", "nodes": "nope"}, "nodes is not a list"),
        ({"request_id": "r", "nodes": [{"id": "a", "type": "Robot"}]}, "unknown label"),
        ({"request_id": "r", "nodes": [{"type": "Decision"}]}, "node without an id"),
        ({"request_id": "r", "nodes": [{"id": "", "type": "Decision"}]}, "empty id"),
        (
            {
                "request_id": "r",
                "nodes": [{"id": "r", "type": "Decision"}],
                "edges": [{"type": "EATS", "from": "r", "to": "r"}],
            },
            "unknown relationship",
        ),
        (
            {
                "request_id": "r",
                "nodes": [{"id": "r", "type": "Decision"}],
                "edges": [{"type": "HAS_CLAIM", "from": "r", "to": "ghost"}],
            },
            "edge endpoint missing from the trace",
        ),
        (
            {
                "request_id": "r",
                "nodes": [
                    {"id": "r", "type": "Decision"},
                    {"id": "e", "type": "Evidence"},
                ],
                "edges": [
                    {
                        "type": "CONFLICTS_WITH",
                        "from": "e",
                        "to": "e",
                        "kind": "vibes",
                    }
                ],
            },
            "unknown conflict kind",
        ),
    ],
)
def test_malformed_traces_are_rejected_without_writing(driver, bad, because):
    sink = Neo4jGraphSink(driver)

    with pytest.raises(TraceContractError):
        validate_trace(bad)

    assert sink.write_trace(bad) is False, because
    assert driver.calls == [], "a rejected trace must not reach the database"
    assert sink.last_error


@pytest.mark.parametrize("bad", [None, 42, "a string", [1, 2, 3]])
def test_non_mapping_traces_are_rejected(driver, bad):
    sink = Neo4jGraphSink(driver)
    assert sink.write_trace(bad) is False
    assert driver.calls == []


def test_a_trace_with_nothing_to_write_is_not_an_error(driver):
    sink = Neo4jGraphSink(driver)
    assert sink.write_trace({"request_id": "r", "nodes": [], "edges": []}) is True
    assert driver.calls == []


def test_unstorable_property_values_are_dropped_not_stringified(driver):
    sink = Neo4jGraphSink(driver)
    sink.write_trace(
        {
            "request_id": "req-nested",
            "nodes": [
                {
                    "id": "req-nested",
                    "type": "Decision",
                    "nested": {"not": "storable"},
                    "indices": [0, 1, 2],
                    "score": 0.5,
                    "flag": True,
                    "nothing": None,
                }
            ],
            "edges": [],
        }
    )
    props = driver.node_props("Decision")[0]
    assert "nested" not in props
    assert props["indices"] == [0, 1, 2]
    assert props["score"] == 0.5
    assert props["flag"] is True
    assert props["nothing"] is None


# ---------------------------------------------------------------------------
# 10 & 11. driver failure is logged, swallowed, and changes nothing
# ---------------------------------------------------------------------------
def test_a_driver_exception_is_logged_and_swallowed(trace, caplog):
    driver = FakeDriver(fail_on=lambda cypher: "Evidence" in cypher)
    sink = Neo4jGraphSink(driver)

    with caplog.at_level(logging.ERROR):
        assert sink.write_trace(trace) is False

    assert "Neo4j write failed" in caplog.text
    assert REQUEST_ID in caplog.text
    assert sink.last_error and "simulated Neo4j failure" in sink.last_error


def test_a_failed_transaction_writes_nothing(trace):
    """The write is all-or-nothing, so no half-written decision survives."""
    driver = FakeDriver(fail_on=lambda cypher: "CONFLICTS_WITH" in cypher)
    sink = Neo4jGraphSink(driver)

    assert sink.write_trace(trace) is False
    assert FakeGraph.from_driver(driver).nodes == {}


def test_an_unavailable_server_does_not_raise(trace, caplog):
    driver = FakeDriver(fail_on_session=True)
    sink = Neo4jGraphSink(driver)

    with caplog.at_level(logging.ERROR):
        assert sink.write_trace(trace) is False
    assert "cannot open a session" in caplog.text


def test_safe_write_trace_swallows_a_sink_that_raises(trace, caplog):
    class ExplodingSink:
        def write_trace(self, trace):
            raise RuntimeError("sink itself is broken")

    with caplog.at_level(logging.ERROR):
        assert safe_write_trace(ExplodingSink(), trace) is False
    assert "decision and trace are unaffected" in caplog.text


def test_safe_write_trace_handles_a_missing_sink(trace):
    assert safe_write_trace(None, trace) is False


def test_safe_write_trace_reports_a_refused_write(trace, caplog):
    class RefusingSink:
        def write_trace(self, trace):
            return False

    with caplog.at_level(logging.WARNING):
        assert safe_write_trace(RefusingSink(), trace) is False
    assert "reported a failed write" in caplog.text


def test_decision_and_trace_survive_an_unavailable_neo4j(trace):
    """Rule: the trace must still be usable by the UI with no Neo4j.

    Stands in for the integration contract: whatever the sink does, the
    trace the caller holds is the same object, with the same decision and
    the same nodes and edges, afterwards.
    """
    import copy

    before = copy.deepcopy(trace)

    failing = Neo4jGraphSink(FakeDriver(fail_on=lambda cypher: True))
    assert safe_write_trace(failing, trace) is False
    assert trace == before, "a failed graph write must not mutate the trace"

    assert safe_write_trace(None, trace) is False
    assert trace == before

    # And the decision the UI reads is still right there.
    assert trace["decision"] == "ESCALATE"
    assert trace["headline"]
    assert len(trace["nodes"]) == len(before["nodes"])
    assert len(trace["edges"]) == len(before["edges"])


def test_the_null_sink_accepts_everything(trace):
    sink = NullGraphSink()
    assert safe_write_trace(sink, trace) is True
    assert sink.written == 1


def test_the_sink_requires_a_driver():
    with pytest.raises(ValueError):
        Neo4jGraphSink(None)


def test_closing_the_sink_closes_the_driver(driver, sink):
    sink.close()
    assert driver.closed is True
