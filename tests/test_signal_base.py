import pytest

from app.evidence.base import Signal
from app.evidence.stubs import FixedSignal
from app.schemas import EvidenceItem, ReasonCode, SignalResult


class CrashingSignal(Signal):
    name = "relevance"

    def score(self, query, answer, evidence):
        raise RuntimeError("model exploded")


class WrongTypeSignal(Signal):
    name = "freshness"

    def score(self, query, answer, evidence):
        return 0.5  # should be a SignalResult, not a float


EVIDENCE = [EvidenceItem(text="18 casual leaves.")]


def test_cannot_instantiate_abstract_signal():
    with pytest.raises(TypeError):
        Signal()


def test_fixed_signal_returns_its_value():
    result = FixedSignal("relevance", 0.9).run("q", "a", EVIDENCE)
    assert result.value == 0.9
    assert result.details["stub"] is True


def test_run_adds_latency():
    result = FixedSignal("relevance", 0.9).run("q", "a", EVIDENCE)
    assert result.details["latency_ms"] >= 0


def test_crashing_signal_fails_safe():
    result = CrashingSignal().run("q", "a", EVIDENCE)
    assert result.value is None
    assert result.reasons[0].code == ReasonCode.SIGNAL_UNAVAILABLE
    assert "model exploded" not in str(result)


def test_wrong_return_type_fails_safe():
    result = WrongTypeSignal().run("q", "a", EVIDENCE)
    assert result.value is None
    assert result.reasons[0].code == ReasonCode.SIGNAL_UNAVAILABLE
    