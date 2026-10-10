"""Unit tests for the Evidence Intelligence adapter.

These use a fake engine, so they run without downloading or loading any model.
The model-backed end-to-end checks live in
tests/integration/test_evidence_integration.py.
"""

import datetime

import pytest

from aegis_core.evidence.engine import EvidenceResult
from app.evidence.evidence_intelligence import (
    EvidenceIntelligence,
    evidence_intelligence_signals,
)
from app.schemas import EvidenceItem, ReasonCode


def make_result(**overrides) -> EvidenceResult:
    """An engine result with no findings, overridable per signal."""
    signals = {
        "relevance": {
            "value": 0.88,
            "reasons": ["Strong semantic match found (max similarity: 0.78)"],
            "details": {
                "relevant_count": 2,
                "total_evidence_count": 2,
                "similarity_threshold": 0.3,
            },
        },
        "entailment": {
            "value": 0.99,
            "reasons": ["Strong support: 2/2 claims entailed by evidence"],
            "details": {
                "claims": [
                    {"claim": "A.", "label": "ENTAILMENT", "score": 0.99},
                    {"claim": "B.", "label": "ENTAILMENT", "score": 0.97},
                ]
            },
        },
        "contradiction": {
            "value": 0.0,
            "reasons": ["No contradiction detected between answer and evidence"],
            "details": {key: [] for key, _s, _p in _CONFLICT_SHAPE},
        },
        "completeness": {
            "value": 1.0,
            "reasons": ["Evidence covers all 2 aspect(s) of the query"],
            "details": {"missing_aspects": [], "total_aspects": 2},
        },
    }
    signals.update(overrides)
    return EvidenceResult(
        decision_ready=True,
        signals=signals,
        reasons=[],
        timing_ms={name: 12.5 for name in signals},
        metadata={"evidence_count": 2},
    )


_CONFLICT_SHAPE = (
    ("numeric_mismatches", "numeric mismatch", "numeric mismatches"),
    ("date_mismatches", "date mismatch", "date mismatches"),
    ("answer_vs_evidence_conflicts", "a", "b"),
    ("evidence_vs_evidence_conflicts", "a", "b"),
    ("version_conflicts", "version conflict", "version conflicts"),
)


class FakeEngine:
    """Records every call so tests can assert how often it ran."""

    def __init__(self, result=None, error=None):
        self.result = result if result is not None else make_result()
        self.error = error
        self.calls = []

    def evaluate(self, query, answer, evidence, evidence_metadata=None):
        self.calls.append(
            {
                "query": query,
                "answer": answer,
                "evidence": evidence,
                "evidence_metadata": evidence_metadata,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def evidence():
    return [
        EvidenceItem(
            text="Employees are entitled to 18 casual leaves per year.",
            source="policy.pdf",
            date=datetime.date(2026, 8, 1),
            version="v3",
        ),
        EvidenceItem(text="Leave is granted annually.", source="handbook.pdf"),
    ]


def signals_for(engine):
    return {s.name: s for s in evidence_intelligence_signals(engine=engine)}


# --------------------------------------------------------------------------
# Evidence shape: EvidenceItem -> texts + metadata
# --------------------------------------------------------------------------
def test_evidence_items_become_texts_and_metadata(evidence):
    engine = FakeEngine()
    signals_for(engine)["relevance"].run("q", "a", evidence)

    call = engine.calls[0]
    assert call["evidence"] == [
        "Employees are entitled to 18 casual leaves per year.",
        "Leave is granted annually.",
    ]
    assert call["evidence_metadata"] == [
        {"source": "policy.pdf", "version": "v3", "date": "2026-08-01"},
        {"source": "handbook.pdf", "version": None, "date": None},
    ]


def test_dates_are_passed_as_iso_strings(evidence):
    engine = FakeEngine()
    signals_for(engine)["contradiction"].run("q", "a", evidence)

    sent = engine.calls[0]["evidence_metadata"][0]["date"]
    assert sent == "2026-08-01"
    assert isinstance(sent, str)


def test_metadata_is_omitted_when_no_item_carries_any(evidence):
    """The engine can skip its version pass when there is nothing to compare."""
    engine = FakeEngine()
    bare = [EvidenceItem(text="Some passage with no metadata at all.")]
    signals_for(engine)["relevance"].run("q", "a", bare)

    assert engine.calls[0]["evidence_metadata"] is None


# --------------------------------------------------------------------------
# One engine call per request, not one per signal
# --------------------------------------------------------------------------
def test_four_signals_share_a_single_engine_call(evidence):
    engine = FakeEngine()
    for signal in evidence_intelligence_signals(engine=engine):
        signal.run("same query", "same answer", evidence)

    assert len(engine.calls) == 1


def test_a_changed_request_triggers_a_new_engine_call(evidence):
    engine = FakeEngine()
    signals = signals_for(engine)

    signals["relevance"].run("query one", "answer", evidence)
    signals["relevance"].run("query two", "answer", evidence)
    assert len(engine.calls) == 2

    # Evidence metadata is part of the identity of a request.
    changed = [evidence[0].model_copy(update={"version": "v9"}), evidence[1]]
    signals["relevance"].run("query two", "answer", changed)
    assert len(engine.calls) == 3


def test_every_signal_reports_its_own_value(evidence):
    engine = FakeEngine()
    signals = signals_for(engine)
    values = {
        name: signal.run("q", "a", evidence).value for name, signal in signals.items()
    }

    assert values == {
        "relevance": 0.88,
        "entailment": 0.99,
        "contradiction": 0.0,
        "completeness": 1.0,
    }


# --------------------------------------------------------------------------
# Contradiction keeps its inverted meaning
# --------------------------------------------------------------------------
def test_contradiction_is_not_inverted_by_the_adapter(evidence):
    """High contradiction must stay high; scoring.py applies 1 - value."""
    engine = FakeEngine(
        make_result(
            contradiction={
                "value": 0.97,
                "reasons": ["Numeric mismatch detected: 18 vs 12"],
                "details": {
                    "numeric_mismatches": [{"answer": 18, "evidence": 12}],
                    "date_mismatches": [],
                    "answer_vs_evidence_conflicts": [{"index": 0}],
                    "evidence_vs_evidence_conflicts": [],
                    "version_conflicts": [],
                },
            }
        )
    )
    result = signals_for(engine)["contradiction"].run("q", "a", evidence)

    assert result.value == 0.97


# --------------------------------------------------------------------------
# Reasons: findings become Reason objects, commentary does not
# --------------------------------------------------------------------------
def test_a_clean_signal_raises_no_reasons(evidence):
    engine = FakeEngine()
    for signal in evidence_intelligence_signals(engine=engine):
        assert signal.run("q", "a", evidence).reasons == []


def test_engine_reasons_are_always_preserved_in_details(evidence):
    """Informational text is kept even when it must not become a Reason."""
    engine = FakeEngine()
    result = signals_for(engine)["contradiction"].run("q", "a", evidence)

    assert result.reasons == []
    assert result.details["engine_reasons"] == [
        "No contradiction detected between answer and evidence"
    ]


def test_unsupported_claims_become_reasons_naming_the_claim(evidence):
    engine = FakeEngine(
        make_result(
            entailment={
                "value": 0.03,
                "reasons": ["Weak support: 0/2 claims entailed"],
                "details": {
                    "claims": [
                        {"claim": "Leave is 18 days.", "label": "CONTRADICTION"},
                        {"claim": "Refunds take 30 days.", "label": "NEUTRAL"},
                        {"claim": "Leave is annual.", "label": "ENTAILMENT"},
                    ]
                },
            }
        )
    )
    result = signals_for(engine)["entailment"].run("q", "a", evidence)

    assert all(r.code == ReasonCode.UNSUPPORTED_CLAIM for r in result.reasons)
    messages = " ".join(r.message for r in result.reasons)
    assert "2 of 3 claims" in messages
    assert "Leave is 18 days." in messages
    assert "is contradicted by" in messages
    assert "Refunds take 30 days." in messages
    assert "is not backed by" in messages
    assert "Leave is annual." not in messages


def test_conflicts_become_reasons_with_correct_plurals(evidence):
    engine = FakeEngine(
        make_result(
            contradiction={
                "value": 1.0,
                "reasons": [],
                "details": {
                    "numeric_mismatches": [{"a": 18, "b": 12}, {"a": 30, "b": 45}],
                    "date_mismatches": [],
                    "answer_vs_evidence_conflicts": [{"index": 0}],
                    "evidence_vs_evidence_conflicts": [],
                    "version_conflicts": [],
                },
            }
        )
    )
    result = signals_for(engine)["contradiction"].run("q", "a", evidence)
    messages = [r.message for r in result.reasons]

    assert "The evidence shows 2 numeric mismatches." in messages
    assert (
        "The evidence shows 1 conflict between the answer and the evidence."
        in messages
    )
    assert all(r.code == ReasonCode.CONTRADICTION for r in result.reasons)
    assert not any("mismatchess" in m for m in messages)


def test_uncovered_query_aspects_become_a_reason(evidence):
    engine = FakeEngine(
        make_result(
            completeness={
                "value": 0.5,
                "reasons": [],
                "details": {
                    "missing_aspects": ["what is the refund policy"],
                    "total_aspects": 2,
                },
            }
        )
    )
    result = signals_for(engine)["completeness"].run("q", "a", evidence)

    assert len(result.reasons) == 1
    assert result.reasons[0].code == ReasonCode.INCOMPLETE_EVIDENCE
    assert "1 of 2 parts" in result.reasons[0].message
    assert "what is the refund policy" in result.reasons[0].message


def test_off_topic_evidence_becomes_a_relevance_reason(evidence):
    engine = FakeEngine(
        make_result(
            relevance={
                "value": 0.2,
                "reasons": [],
                "details": {
                    "relevant_count": 1,
                    "total_evidence_count": 3,
                    "similarity_threshold": 0.3,
                },
            }
        )
    )
    result = signals_for(engine)["relevance"].run("q", "a", evidence)

    assert len(result.reasons) == 1
    assert result.reasons[0].code == ReasonCode.LOW_RELEVANCE
    assert "2 of 3 evidence passages are not related" in result.reasons[0].message


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------
def test_engine_failure_degrades_every_signal(evidence):
    """run() must catch the error and never let it reach the evaluator."""
    engine = FakeEngine(error=RuntimeError("NLI model unavailable"))

    for signal in evidence_intelligence_signals(engine=engine):
        result = signal.run("q", "a", evidence)
        assert result.value is None
        assert [r.code for r in result.reasons] == [ReasonCode.SIGNAL_UNAVAILABLE]


def test_a_failure_is_never_cached_as_a_success(evidence):
    """A recovered engine must be retried, not served a stale failure."""
    engine = FakeEngine(error=RuntimeError("transient"))
    intelligence = EvidenceIntelligence(engine)

    with pytest.raises(RuntimeError):
        intelligence.result_for("q", "a", evidence)

    engine.error = None
    assert intelligence.result_for("q", "a", evidence) is engine.result


def test_timing_is_reported_per_signal(evidence):
    engine = FakeEngine()
    result = signals_for(engine)["relevance"].run("q", "a", evidence)

    assert result.details["engine_latency_ms"] == 12.5
    # base.run() adds its own wall-clock measurement.
    assert "latency_ms" in result.details
