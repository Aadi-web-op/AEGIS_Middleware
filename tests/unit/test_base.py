"""Unit tests for shared signal primitives and engine input normalisation.

Pure-Python, no model download required.
"""

import pytest

from aegis_core.signals.base import SignalResult, SignalName, BaseSignal
from aegis_core.evidence.engine import EvidenceEngine


# ------------------------------------------------------------------
# SignalResult validation
# ------------------------------------------------------------------
def test_signal_result_accepts_valid_range():
    r = SignalResult(signal=SignalName.RELEVANCE, value=0.5)
    assert r.value == 0.5
    assert r.reasons == []
    assert r.details == {}


def test_signal_result_rejects_below_zero():
    with pytest.raises(ValueError):
        SignalResult(signal=SignalName.RELEVANCE, value=-0.1)


def test_signal_result_rejects_above_one():
    with pytest.raises(ValueError):
        SignalResult(signal=SignalName.RELEVANCE, value=1.5)


def test_signal_result_accepts_bounds():
    SignalResult(signal=SignalName.RELEVANCE, value=0.0)
    SignalResult(signal=SignalName.RELEVANCE, value=1.0)


# ------------------------------------------------------------------
# BaseSignal default helpers
# ------------------------------------------------------------------
def test_handle_empty_evidence():
    class Dummy(BaseSignal):
        @property
        def signal_name(self):
            return SignalName.RELEVANCE

        def evaluate(self, query, answer, evidence, **kwargs):
            return SignalResult(signal=self.signal_name, value=1.0)

    d = Dummy()
    r = d._handle_empty_evidence(SignalName.RELEVANCE, default_value=0.0)
    assert r.value == 0.0
    assert r.signal == SignalName.RELEVANCE
    assert r.details["evidence_count"] == 0


# ------------------------------------------------------------------
# Evidence normalisation
# ------------------------------------------------------------------
def test_normalise_evidence_drops_none_and_empty():
    engine = EvidenceEngine()
    out = engine._normalise_evidence([" real ", "", None, "text"])
    assert out == ["real", "text"]


def test_normalise_evidence_dedupes_case_insensitively():
    engine = EvidenceEngine()
    out = engine._normalise_evidence(
        ["Employees get 18 leaves.", "EMPLOYEES GET 18 LEAVES.", "Other."]
    )
    assert len(out) == 2
    assert out[0] == "Employees get 18 leaves."
    assert out[1] == "Other."


def test_normalise_evidence_rejects_non_string():
    engine = EvidenceEngine()
    out = engine._normalise_evidence(["keep", 42, {"a": 1}])
    assert out == ["keep"]


def test_normalise_evidence_empty():
    engine = EvidenceEngine()
    assert engine._normalise_evidence([]) == []
    assert engine._normalise_evidence(None) == []
