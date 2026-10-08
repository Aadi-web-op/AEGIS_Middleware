import pytest

from app.core.config import UnknownProfileError
from app.core.evaluator import Evaluator
from app.evidence.base import Signal
from app.evidence.stubs import FixedSignal
from app.schemas import (
    Decision,
    EvaluateRequest,
    Reason,
    ReasonCode,
    RecommendedAction,
    SignalResult,
)

GOOD = dict(relevance=0.95, entailment=0.95, contradiction=0.02,
            freshness=0.9, completeness=0.9, ambiguity=0.04)

REQ = EvaluateRequest(
    query="How many casual leaves?",
    answer="18.",
    evidence=[{"text": "18 casual leaves.", "source": "policy_2026.pdf"}],
)


def stubs(**overrides):
    values = {**GOOD, **overrides}
    return [FixedSignal(name, v) for name, v in values.items()]


class CountingSignal(Signal):
    name = "relevance"

    def __init__(self):
        self.calls = 0

    def score(self, query, answer, evidence):
        self.calls += 1
        return SignalResult(value=1.0)


class CrashingSignal(Signal):
    name = "contradiction"

    def score(self, query, answer, evidence):
        raise RuntimeError("model exploded")


class ClarifyingAmbiguity(Signal):
    name = "ambiguity"

    def score(self, query, answer, evidence):
        return SignalResult(value=0.8, details={"clarifying_question": "Which leave type?"})


class ConflictingContradiction(Signal):
    name = "contradiction"

    def score(self, query, answer, evidence):
        return SignalResult(
            value=0.9,
            reasons=[Reason(code=ReasonCode.CONTRADICTION,
                            message="Two sources disagree on the leave count.")],
        )


def without(name):
    return [s for s in stubs() if s.name != name]


def test_clean_request_is_answered():
    resp = Evaluator(stubs()).evaluate(REQ)
    assert resp.decision == Decision.ANSWER
    assert resp.signals.relevance == 0.95
    assert resp.degraded is False
    assert resp.latency_ms is not None
    assert resp.policy_version == "0.1.0"
    assert resp.request_id


def test_no_evidence_abstains_without_calling_any_signal():
    counter = CountingSignal()
    resp = Evaluator([counter]).evaluate(EvaluateRequest(query="Q?", answer="A."))
    assert resp.decision == Decision.ABSTAIN
    assert resp.reasons[0].code == ReasonCode.NO_EVIDENCE
    assert counter.calls == 0


def test_contradiction_escalates_even_though_score_is_high():
    resp = Evaluator(stubs(contradiction=0.9)).evaluate(REQ)
    assert resp.decision == Decision.ESCALATE


def test_crashing_signal_degrades_and_escalates():
    resp = Evaluator(without("contradiction") + [CrashingSignal()]).evaluate(REQ)
    assert resp.degraded is True
    assert resp.decision == Decision.ESCALATE
    assert resp.signals.contradiction is None


def test_no_registered_signals_fails_closed():
    resp = Evaluator([]).evaluate(REQ)
    assert resp.decision == Decision.ABSTAIN
    assert resp.degraded is True


def test_unknown_profile_raises():
    with pytest.raises(UnknownProfileError):
        Evaluator(stubs()).evaluate(REQ.model_copy(update={"profile": "paranoid"}))


def test_same_request_standard_vs_strict():
    signals = stubs(relevance=0.9, entailment=0.9, contradiction=0.1,
                    freshness=0.8, completeness=0.8, ambiguity=0.1)
    evaluator = Evaluator(signals)
    assert evaluator.evaluate(REQ).decision == Decision.ANSWER
    strict = evaluator.evaluate(REQ.model_copy(update={"profile": "strict"}))
    assert strict.decision == Decision.CAVEAT


def test_clarifying_question_passes_through():
    others = [s for s in stubs() if s.name != "ambiguity"]
    resp = Evaluator(others + [ClarifyingAmbiguity()]).evaluate(REQ)
    assert resp.decision == Decision.ESCALATE
    assert resp.recommended_action == RecommendedAction.ASK_CLARIFYING_QUESTION
    assert resp.clarifying_question == "Which leave type?"


def test_signal_reasons_reach_the_response():
    resp = Evaluator(without("contradiction") + [ConflictingContradiction()]).evaluate(REQ)
    assert any("disagree on the leave count" in r.message for r in resp.reasons)


def test_time_sensitive_flag_controls_stale_caveat():
    evaluator = Evaluator(stubs(freshness=0.3))
    assert evaluator.evaluate(REQ).decision == Decision.CAVEAT
    relaxed = REQ.model_copy(update={"time_sensitive": False})
    assert evaluator.evaluate(relaxed).decision == Decision.ANSWER


def test_duplicate_signal_names_rejected():
    with pytest.raises(ValueError):
        Evaluator([FixedSignal("relevance", 1), FixedSignal("relevance", 1)])


def test_unknown_signal_name_rejected():
    with pytest.raises(ValueError):
        Evaluator([FixedSignal("vibes", 1)])
        