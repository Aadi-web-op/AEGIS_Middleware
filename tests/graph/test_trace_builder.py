"""The proposed trace builder: does it only claim what the signals found?

These cover the places where the mapping could invent structure -- an
edge for a conflict with no reliable pair, a supersession direction that
cannot be established, an evidence index the trace has no node for.
"""

from __future__ import annotations

from app.graph.contract import EVIDENCE_PREVIEW_CHARS, validate_trace
from app.graph.trace_builder import build_trace


def _edges(trace, relationship):
    return [e for e in trace["edges"] if e["type"] == relationship]


def _nodes(trace, node_type):
    return [n for n in trace["nodes"] if n["type"] == node_type]


EVIDENCE = [
    {"text": "18 casual leaves per year.", "source": "a.pdf", "version": "1"},
    {"text": "12 casual leaves per year.", "source": "b.pdf", "version": "2"},
]


def test_the_canonical_trace_satisfies_the_contract(trace):
    assert validate_trace(trace)["request_id"] == trace["request_id"]


def test_a_minimal_trace_is_just_a_decision():
    trace = build_trace(request_id="r1", decision="ABSTAIN")
    assert validate_trace(trace)
    assert trace["nodes"] == [
        {"id": "r1", "type": "Decision", "request_id": "r1", "decision": "ABSTAIN"}
    ]
    assert trace["edges"] == []
    # An absent headline is left out rather than stored as a null property.
    assert trace["headline"] is None


def test_an_ineligible_conflict_gets_no_edge():
    """An answer-vs-evidence conflict has one index, so no pair edge."""
    trace = build_trace(
        request_id="r2",
        decision="CAVEAT",
        evidence=EVIDENCE,
        contradiction_details={
            "conflicts": [
                {
                    "kind": "numeric",
                    "scope": "answer_vs_evidence",
                    "index_a": None,
                    "index_b": 1,
                    "value_a": "18",
                    "value_b": "12",
                    "graph_edge_eligible": False,
                }
            ]
        },
    )
    assert _edges(trace, "CONFLICTS_WITH") == []


def test_an_eligible_conflict_gets_one_edge_carrying_its_values():
    trace = build_trace(
        request_id="r3",
        decision="ESCALATE",
        evidence=EVIDENCE,
        contradiction_details={
            "conflicts": [
                {
                    "kind": "numeric",
                    "scope": "evidence_vs_evidence",
                    "index_a": 0,
                    "index_b": 1,
                    "value_a": "18",
                    "value_b": "12",
                    "reason": "Numeric mismatch: 18 vs 12.",
                    "severity": "high",
                    "score": 1.0,
                    "graph_edge_eligible": True,
                }
            ]
        },
    )
    edges = _edges(trace, "CONFLICTS_WITH")
    assert len(edges) == 1
    assert edges[0]["kind"] == "numeric"
    assert edges[0]["value_a"] == "18"
    assert edges[0]["value_b"] == "12"
    assert edges[0]["from"] == "r3:evidence:0"
    assert edges[0]["to"] == "r3:evidence:1"


def test_supersedes_is_omitted_when_the_order_cannot_be_established():
    evidence = [
        {"text": "a", "source": "p.pdf", "version": "draft"},
        {"text": "b", "source": "p.pdf", "version": "final"},
    ]
    trace = build_trace(
        request_id="r4",
        decision="ESCALATE",
        evidence=evidence,
        contradiction_details={
            "conflicts": [
                {
                    "kind": "version",
                    "scope": "version",
                    "index_a": 0,
                    "index_b": 1,
                    "value_a": "draft",
                    "value_b": "final",
                    "graph_edge_eligible": True,
                }
            ]
        },
    )
    assert _edges(trace, "CONFLICTS_WITH"), "the conflict itself is still recorded"
    assert _edges(trace, "SUPERSEDES") == [], "'draft' vs 'final' has no numeric order"


def test_supersedes_uses_the_date_when_versions_are_numeric():
    evidence = [
        {"text": "a", "source": "p.pdf", "version": "3", "date": "2026-01-01"},
        {"text": "b", "source": "p.pdf", "version": "2", "date": "2026-06-01"},
    ]
    trace = build_trace(
        request_id="r5",
        decision="ESCALATE",
        evidence=evidence,
        contradiction_details={
            "conflicts": [
                {
                    "kind": "version",
                    "scope": "version",
                    "index_a": 0,
                    "index_b": 1,
                    "graph_edge_eligible": True,
                }
            ]
        },
    )
    edges = _edges(trace, "SUPERSEDES")
    assert len(edges) == 1
    # The later date wins over the higher version number.
    assert edges[0]["from"] == "doc:p.pdf@2"
    assert edges[0]["to"] == "doc:p.pdf@3"


def test_an_unknown_evidence_index_is_skipped_not_invented(caplog):
    trace = build_trace(
        request_id="r6",
        decision="ANSWER",
        evidence=EVIDENCE,
        entailment_details={
            "claims": [
                {
                    "claim_index": 0,
                    "claim": "A claim.",
                    "status": "SUPPORTED",
                    "support": 0.9,
                    "supporting_evidence_indices": [0, 99],
                    "contradicting_evidence_indices": [],
                }
            ]
        },
    )
    supported = _edges(trace, "SUPPORTED_BY")
    assert len(supported) == 1
    assert supported[0]["to"] == "r6:evidence:0"
    assert len(_nodes(trace, "Evidence")) == 2


def test_evidence_carries_a_preview_and_never_the_passage():
    long_text = "z" * 900
    trace = build_trace(
        request_id="r7",
        decision="ANSWER",
        evidence=[{"text": long_text, "source": "s.pdf"}],
    )
    evidence = _nodes(trace, "Evidence")[0]
    assert "text" not in evidence
    assert len(evidence["preview"]) == EVIDENCE_PREVIEW_CHARS


def test_a_chunk_id_is_used_as_the_evidence_identity_when_supplied():
    trace = build_trace(
        request_id="r8",
        decision="ANSWER",
        evidence=[{"text": "a", "source": "s.pdf", "chunk_id": "chunk-42"}],
    )
    assert _nodes(trace, "Evidence")[0]["id"] == "chunk-42"


def test_documents_are_shared_across_evidence_from_the_same_version():
    trace = build_trace(
        request_id="r9",
        decision="ANSWER",
        evidence=[
            {"text": "a", "source": "s.pdf", "version": "1"},
            {"text": "b", "source": "s.pdf", "version": "1"},
        ],
    )
    assert len(_nodes(trace, "Document")) == 1
    assert len(_edges(trace, "FROM")) == 2


def test_evidence_without_a_source_gets_no_document():
    trace = build_trace(
        request_id="r10", decision="ANSWER", evidence=[{"text": "a"}]
    )
    assert _nodes(trace, "Document") == []
    assert _edges(trace, "FROM") == []


def test_about_edges_are_only_drawn_where_attribution_is_known():
    trace = build_trace(
        request_id="r11",
        decision="CAVEAT",
        evidence=EVIDENCE,
        entailment_details={
            "claims": [
                {
                    "claim_index": 0,
                    "claim": "Unsupported.",
                    "status": "UNSUPPORTED",
                    "support": 0.1,
                    "supporting_evidence_indices": [],
                    "contradicting_evidence_indices": [],
                }
            ]
        },
        reasons=[
            {"code": "UNSUPPORTED_CLAIM", "message": "m1"},
            {"code": "LOW_RELEVANCE", "message": "m2"},
        ],
    )
    about = _edges(trace, "ABOUT")
    assert len(about) == 1, "LOW_RELEVANCE is not attributable, so it gets no ABOUT"
    assert about[0]["to"] == "r11:claim:0"
    assert len(_edges(trace, "BECAUSE")) == 2


def test_a_supported_claim_gets_no_unsupported_attribution():
    trace = build_trace(
        request_id="r12",
        decision="ANSWER",
        evidence=EVIDENCE,
        entailment_details={
            "claims": [
                {
                    "claim_index": 0,
                    "claim": "Supported.",
                    "status": "SUPPORTED",
                    "support": 0.95,
                    "supporting_evidence_indices": [0],
                    "contradicting_evidence_indices": [],
                }
            ]
        },
        reasons=[{"code": "UNSUPPORTED_CLAIM", "message": "m"}],
    )
    assert _edges(trace, "ABOUT") == []


def test_reason_codes_may_be_enum_members():
    from app.schemas import Reason, ReasonCode

    reason = Reason(code=ReasonCode.CONTRADICTION, message="m")
    trace = build_trace(
        request_id="r13", decision="ESCALATE", reasons=[reason.model_dump()]
    )
    assert _nodes(trace, "Reason")[0]["code"] == "CONTRADICTION"
    assert validate_trace(trace)


def test_the_builder_is_deterministic(signal_details):
    from tests.graph.conftest import EVIDENCE as CANONICAL, REASONS, REQUEST_ID

    kwargs = dict(
        request_id=REQUEST_ID,
        decision="ESCALATE",
        headline="h",
        evidence=CANONICAL,
        entailment_details=signal_details["entailment"],
        contradiction_details=signal_details["contradiction"],
        reasons=REASONS,
    )
    assert build_trace(**kwargs) == build_trace(**kwargs)
