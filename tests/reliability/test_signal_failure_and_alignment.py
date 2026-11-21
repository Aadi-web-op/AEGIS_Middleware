"""Signal-level reliability: atomic verification, model failure, index alignment.

Deterministic. The NLI runner is replaced by `FakeNLI` / `BrokenNLI` from
tests/conftest.py and the engine by a recording fake, so no model is loaded.
"""

import datetime

from aegis_core.evidence.engine import EvidenceResult
from aegis_core.signals.contradiction import ContradictionSignal
from aegis_core.signals.entailment import EntailmentSignal
from app.evidence.evidence_intelligence import (
    _normalised_payload,
    _remap_indices,
    evidence_intelligence_signals,
)
from app.schemas import EvidenceItem, ReasonCode
from tests.conftest import BrokenNLI, FakeNLI

GROWTH = "Population growth is an important driver of urban expansion."
ANSWER = "Urban expansion is mainly caused by population growth and infrastructure development."
ATOM_A = "Urban expansion is mainly caused by population growth."
ATOM_B = "Urban expansion is mainly caused by infrastructure development."

YES = (0.95, 0.01, 0.04)
NO = (0.02, 0.90, 0.08)


def entailment(table):
    signal = EntailmentSignal()
    signal.nli = FakeNLI(table)
    return signal


# ------------------------------------------------------------------ atomic verification
def test_half_supported_sentence_becomes_one_supported_and_one_unsupported_claim():
    result = entailment({(GROWTH, ATOM_A): YES}).evaluate("q", ANSWER, [GROWTH])
    claims = result.details["claims"]

    assert [c["claim"] for c in claims] == [ATOM_A, ATOM_B]
    assert [c["status"] for c in claims] == ["SUPPORTED", "UNSUPPORTED"]
    assert claims[0]["supporting_evidence_indices"] == [0]
    assert claims[1]["evidence_indices"] == []
    assert all(c["decomposed"] and c["source_sentence"] == ANSWER for c in claims)
    assert [c["claim_index"] for c in claims] == [0, 1]


def test_sentence_supported_as_a_whole_is_not_decomposed():
    result = entailment({(GROWTH, ANSWER): YES}).evaluate("q", ANSWER, [GROWTH])
    claims = result.details["claims"]
    assert len(claims) == 1
    assert claims[0]["claim"] == ANSWER
    assert claims[0]["decomposed"] is False


def test_contradicted_sentence_is_not_decomposed():
    result = entailment({(GROWTH, ANSWER): NO}).evaluate("q", ANSWER, [GROWTH])
    claims = result.details["claims"]
    assert [c["status"] for c in claims] == ["CONTRADICTED"]


def test_two_passages_can_each_support_one_half():
    a = "Regular physical activity is associated with improved cardiovascular health."
    b = "The magnitude of benefit varies across individuals."
    answer = "Regular exercise generally improves cardiovascular health, although the effect varies by individual."
    table = {
        (a, "Regular exercise generally improves cardiovascular health."): YES,
        (b, "The effect varies by individual."): YES,
    }
    claims = entailment(table).evaluate("q", answer, [a, b]).details["claims"]
    assert [c["status"] for c in claims] == ["SUPPORTED", "SUPPORTED"]
    assert [c["supporting_evidence_indices"] for c in claims] == [[0], [1]]


def test_best_supported_wording_of_an_atom_is_kept():
    ev = "Paris is the largest city in France and its capital."
    answer = "Paris is the capital of France and the largest city."
    table = {
        (ev, "Paris is the capital of France."): YES,
        (ev, "Paris is the largest city."): YES,  # not "...the capital of the largest city."
    }
    claims = entailment(table).evaluate("q", answer, [ev]).details["claims"]
    assert [c["claim"] for c in claims] == ["Paris is the capital of France.", "Paris is the largest city."]
    assert all(c["status"] == "SUPPORTED" for c in claims)


def test_claim_cap_is_reported():
    answer = " ".join(f"Item {i} is covered by rule {i}, rule {i + 100}, and rule {i + 200}." for i in range(6))
    result = entailment({}).evaluate("q", answer, ["Unrelated passage about something else entirely."])
    assert len(result.details["claims"]) == 10
    assert result.details["claims_truncated"] is True


def test_each_claim_carries_grounding_and_raw_probabilities():
    claim = entailment({(GROWTH, ATOM_A): YES}).evaluate("q", ANSWER, [GROWTH]).details["claims"][0]
    assert claim["entailment_probability"] == 0.95
    assert 0.0 <= claim["grounding"] <= 1.0


def test_support_late_in_a_long_passage_is_found():
    """The NLI model truncates its input; long passages are checked in windows."""
    filler = " ".join(f"Clause {i} of the handbook describes an unrelated procedure in detail." for i in range(60))
    tail = "Refunds are issued within 30 days."
    passage = f"{filler} {tail}"
    claim = "Refunds are issued within 30 days."

    class WindowAwareNLI(FakeNLI):
        def infer_batch(self, pairs):
            self.table = {(p, h): YES for p, h in pairs if tail in p and h == claim}
            return super().infer_batch(pairs)

    signal = EntailmentSignal()
    signal.nli = WindowAwareNLI()
    result = signal.evaluate("q", claim, [passage])
    assert max(len(p.split()) for batch in signal.nli.batches for p, _h in batch) <= 140
    assert result.details["claims"][0]["status"] == "SUPPORTED"
    assert result.details["claims"][0]["supporting_evidence_indices"] == [0]


# ------------------------------------------------------------------ model failure
def test_broken_nli_is_flagged_on_the_entailment_details():
    signal = EntailmentSignal()
    signal.nli = BrokenNLI()
    result = signal.evaluate("q", ANSWER, [GROWTH])
    assert result.details["nli_available"] is False
    assert all(c["nli_available"] is False for c in result.details["claims"])


def make_engine_result(**overrides):
    signals = {
        "relevance": {"value": 0.9, "reasons": [], "details": {"relevant_count": 1, "total_evidence_count": 1}},
        "entailment": {"value": 0.9, "reasons": [], "details": {"claims": []}},
        "contradiction": {"value": 0.0, "reasons": [], "details": {"nli_available": True}},
        "completeness": {"value": 1.0, "reasons": [], "details": {"missing_aspects": [], "total_aspects": 1}},
    }
    signals.update(overrides)
    return EvidenceResult(decision_ready=True, signals=signals, reasons=[],
                          timing_ms={k: 1.0 for k in signals}, metadata={})


class FakeEngine:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def evaluate(self, query, answer, evidence, evidence_metadata=None):
        self.calls.append({"evidence": evidence, "evidence_metadata": evidence_metadata})
        return self.result


def run_adapter(result, evidence=None):
    evidence = evidence or [EvidenceItem(text="Leave is 18 days.")]
    engine = FakeEngine(result)
    signals = {s.name: s for s in evidence_intelligence_signals(engine=engine)}
    return {name: s.run("q", "a", evidence) for name, s in signals.items()}, engine


def test_unverified_claims_make_entailment_unavailable_not_zero():
    """A dead NLI model must not be reported as 'the answer is unsupported'."""
    result = make_engine_result(entailment={
        "value": 0.0, "reasons": [],
        "details": {"claims": [{"claim": "Leave is 18 days.", "label": "NEUTRAL", "nli_available": False}]},
    })
    out, _ = run_adapter(result)
    assert out["entailment"].value is None
    assert [r.code for r in out["entailment"].reasons] == [ReasonCode.SIGNAL_UNAVAILABLE]
    assert "NLI model was unavailable" in out["entailment"].reasons[0].message
    # The other signals are unaffected.
    assert out["relevance"].value == 0.9


def test_contradiction_without_nli_is_unavailable_not_clean():
    result = make_engine_result(contradiction={
        "value": 0.0, "reasons": [], "details": {"nli_available": False, "numeric_mismatches": []}})
    out, _ = run_adapter(result)
    assert out["contradiction"].value is None
    assert out["contradiction"].reasons[0].code == ReasonCode.SIGNAL_UNAVAILABLE


def test_rule_based_conflict_survives_an_nli_outage():
    """A numeric mismatch is exact arithmetic; it does not need the model."""
    result = make_engine_result(contradiction={
        "value": 0.83, "reasons": [],
        "details": {"nli_available": False, "numeric_mismatches": [{"value_a": 18, "value_b": 12}]}})
    out, _ = run_adapter(result)
    assert out["contradiction"].value == 0.83
    assert out["contradiction"].reasons[0].code == ReasonCode.CONTRADICTION


def test_embedding_failure_is_unavailable_not_irrelevant():
    result = make_engine_result(
        relevance={"value": 0.0, "reasons": ["Embedding computation failed: boom"], "details": {"error": "boom"}},
        completeness={"value": 0.0, "reasons": ["Embedding computation failed: boom"], "details": {"error": "boom"}},
    )
    out, _ = run_adapter(result)
    assert out["relevance"].value is None
    assert out["completeness"].value is None
    assert out["relevance"].details["model_failure"]


def test_real_contradiction_signal_reports_nli_outage():
    signal = ContradictionSignal()
    signal.nli = BrokenNLI()
    result = signal.evaluate("q", "Leave is 18 days.", ["Leave is granted annually."])
    assert result.details["nli_available"] is False
    assert result.value == 0.0  # the engine's placeholder, which the adapter refuses to pass on


# ------------------------------------------------------------------ evidence index alignment
def item(text, source=None, version=None):
    return EvidenceItem(text=text, source=source, version=version, date=datetime.date(2026, 1, 1))


def test_duplicates_and_blanks_are_dropped_with_an_index_map():
    evidence = [item("A.", "a.pdf"), item("   "), item("a.", "dup.pdf"), item("B.", "b.pdf")]
    texts, metadata, index_map = _normalised_payload(evidence)
    assert texts == ["A.", "B."]
    assert [m["source"] for m in metadata] == ["a.pdf", "b.pdf"]  # metadata stays aligned
    assert index_map == [0, 3]


def test_remap_rewrites_only_index_fields():
    details = {
        "claims": [{"claim": "x", "supporting_evidence_indices": [1], "contradicting_evidence_indices": [0],
                    "evidence_indices": [0, 1], "claim_index": 1}],
        "conflicts": [{"index_a": 0, "index_b": 1, "kind": "numeric"}, {"index_a": None, "index_b": 1}],
        "evidence_count": 2,
    }
    out = _remap_indices(details, [0, 3])
    assert out["claims"][0]["supporting_evidence_indices"] == [3]
    assert out["claims"][0]["evidence_indices"] == [0, 3]
    assert out["claims"][0]["claim_index"] == 1          # not an evidence index
    assert out["conflicts"][0] == {"index_a": 0, "index_b": 3, "kind": "numeric"}
    assert out["conflicts"][1]["index_a"] is None
    assert out["evidence_count"] == 2


def test_adapter_reports_request_indices_when_a_duplicate_precedes_the_support():
    evidence = [item("Intro."), item("intro."), item("Leave is 18 days.", "policy.pdf", "v3")]
    result = make_engine_result(entailment={
        "value": 0.95, "reasons": [],
        "details": {"claims": [{"claim": "Leave is 18 days.", "label": "ENTAILMENT", "status": "SUPPORTED",
                                "support": 0.95, "supporting_evidence_indices": [1],
                                "evidence_indices": [1], "nli_available": True}]},
    })
    out, engine = run_adapter(result, evidence)

    assert engine.calls[0]["evidence"] == ["Intro.", "Leave is 18 days."]
    assert [m["source"] for m in engine.calls[0]["evidence_metadata"]] == [None, "policy.pdf"]
    claim = out["entailment"].details["claims"][0]
    assert claim["supporting_evidence_indices"] == [2]   # request index, not engine index
    assert out["entailment"].details["evidence_dropped"] == 1
    assert out["entailment"].details["evidence_index_map"] == [0, 2]
    # The engine's own (cached) result object is not mutated.
    assert result.signals["entailment"]["details"]["claims"][0]["supporting_evidence_indices"] == [1]


def test_clean_evidence_passes_through_untouched():
    out, _ = run_adapter(make_engine_result())
    assert "evidence_dropped" not in out["entailment"].details
