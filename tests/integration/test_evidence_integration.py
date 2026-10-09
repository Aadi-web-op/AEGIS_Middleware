"""End-to-end checks that the real Evidence Intelligence Engine drives decisions.

The full path under test:

    query + answer + evidence
      -> Evidence Intelligence Engine (relevance, entailment,
         contradiction, completeness)
      -> central evaluator
      -> weighted score + veto rules + risk profile
      -> ANSWER / CAVEAT / ESCALATE / ABSTAIN

These load real models, so they are slow. The adapter's own mapping rules are
covered without models in tests/test_evidence_intelligence.py.

Caveat on freshness and ambiguity: both signals exist on main but are still
wired as FixedSignal in app/evidence/registry.py, pending their owners. Any
assertion here therefore deliberately avoids depending on either value.
"""

import datetime

import pytest

from app.core.evaluator import Evaluator
from app.evidence.evidence_intelligence import evidence_intelligence_signals
from app.evidence.registry import default_signals
from app.schemas import Decision, EvaluateRequest, ReasonCode, RecommendedAction

TODAY = datetime.date.today()


@pytest.fixture(scope="module")
def evaluator(evidence_engine):
    """Evaluator wired to the warmed session engine from conftest."""
    stubs = [s for s in default_signals() if s.name in {"freshness", "ambiguity"}]
    return Evaluator([*evidence_intelligence_signals(engine=evidence_engine), *stubs])


def evaluate(evaluator, query, answer, evidence, profile="standard"):
    return evaluator.evaluate(
        EvaluateRequest(
            query=query, answer=answer, evidence=evidence, profile=profile
        )
    )


def codes(response):
    return {reason.code for reason in response.reasons}


# --------------------------------------------------------------------------
# 1. Fully supported answer
# --------------------------------------------------------------------------
def test_fully_supported_answer_is_returned(evaluator):
    response = evaluate(
        evaluator,
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=[
            {
                "text": "Employees are entitled to 18 casual leaves per year.",
                "source": "policy_2026.pdf",
                "date": TODAY,
                "version": "v3",
            }
        ],
    )

    assert response.decision is Decision.ANSWER
    assert response.recommended_action is RecommendedAction.RETURN_ANSWER
    assert response.reasons == []
    assert response.degraded is False

    # The values came from the engine, not from a constant.
    assert response.signals.relevance > 0.5
    assert response.signals.entailment > 0.8
    assert response.signals.contradiction == pytest.approx(0.0, abs=0.05)
    assert response.signals.completeness == pytest.approx(1.0)


# --------------------------------------------------------------------------
# 2. Empty evidence
# --------------------------------------------------------------------------
def test_empty_evidence_abstains_without_running_any_model(evaluator):
    response = evaluate(
        evaluator,
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=[],
    )

    assert response.decision is Decision.ABSTAIN
    assert response.recommended_action is RecommendedAction.ABSTAIN
    assert codes(response) == {ReasonCode.NO_EVIDENCE}
    # Short-circuited before the signals ran, so nothing was measured.
    assert response.signals.relevance is None
    assert response.signals.entailment is None


# --------------------------------------------------------------------------
# 3. Answer says 18, evidence says 12
# --------------------------------------------------------------------------
def test_numeric_conflict_with_the_answer_escalates(evaluator):
    response = evaluate(
        evaluator,
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=[
            {
                "text": "Employees are entitled to 12 casual leaves per year.",
                "source": "policy_2026.pdf",
                "date": TODAY,
            }
        ],
    )

    assert response.decision is Decision.ESCALATE
    assert response.recommended_action is RecommendedAction.ESCALATE_TO_HUMAN
    assert response.signals.contradiction > 0.6
    assert response.signals.entailment < 0.4
    assert ReasonCode.CONTRADICTION in codes(response)
    assert ReasonCode.UNSUPPORTED_CLAIM in codes(response)


# --------------------------------------------------------------------------
# 4. Two evidence sources disagree with each other
# --------------------------------------------------------------------------
def test_two_sources_that_disagree_escalate(evaluator):
    response = evaluate(
        evaluator,
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=[
            {
                "text": "Employees are entitled to 18 casual leaves per year.",
                "source": "circular_a.pdf",
                "date": TODAY,
                "version": "v2",
            },
            {
                "text": "Employees are entitled to 12 casual leaves per year.",
                "source": "circular_b.pdf",
                "date": TODAY,
                "version": "v1",
            },
        ],
    )

    assert response.decision is Decision.ESCALATE
    assert response.signals.contradiction > 0.6
    assert ReasonCode.CONTRADICTION in codes(response)
    # The answer itself matches one source, so support stays high: the conflict
    # between sources is what forces the escalation.
    assert response.signals.entailment > 0.5


# --------------------------------------------------------------------------
# 5. Evidence covers only part of the question
# --------------------------------------------------------------------------
def test_partially_covered_question_is_caveated(evaluator):
    response = evaluate(
        evaluator,
        query="What is the casual leave policy and what is the refund policy?",
        answer="Employees receive 18 casual leaves per year. Refunds take 30 days.",
        evidence=[
            {
                "text": "Employees are entitled to 18 casual leaves per year.",
                "source": "policy_2026.pdf",
                "date": TODAY,
            }
        ],
    )

    assert response.decision is Decision.CAVEAT
    assert response.recommended_action is RecommendedAction.RETURN_WITH_CAVEAT
    assert response.caveat_text
    assert response.signals.completeness < 1.0
    assert ReasonCode.INCOMPLETE_EVIDENCE in codes(response)
    assert ReasonCode.UNSUPPORTED_CLAIM in codes(response)


# --------------------------------------------------------------------------
# 6. Evidence carries no dates
# --------------------------------------------------------------------------
def test_evidence_without_dates_still_produces_evidence_signals(evaluator):
    """Undated evidence must not break the engine or the metadata mapping.

    What the decision should be in this case depends on freshness, which is
    still a stub, so only the evidence signals are asserted here.
    """
    response = evaluate(
        evaluator,
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=[
            {
                "text": "Employees are entitled to 18 casual leaves per year.",
                "source": "policy.pdf",
            }
        ],
    )

    assert response.signals.relevance is not None
    assert response.signals.entailment > 0.8
    assert response.signals.contradiction == pytest.approx(0.0, abs=0.05)
    assert ReasonCode.SIGNAL_UNAVAILABLE not in codes(response)


# --------------------------------------------------------------------------
# 7. Several claims, only some supported
# --------------------------------------------------------------------------
def test_only_the_unsupported_claim_is_named(evaluator):
    response = evaluate(
        evaluator,
        query="What are the leave and probation rules?",
        answer=(
            "Employees receive 18 casual leaves per year. "
            "Probation lasts six months."
        ),
        evidence=[
            {
                "text": "Employees are entitled to 18 casual leaves per year.",
                "source": "policy_2026.pdf",
                "date": TODAY,
            }
        ],
    )

    assert response.decision is not Decision.ANSWER
    assert ReasonCode.UNSUPPORTED_CLAIM in codes(response)

    messages = " ".join(reason.message for reason in response.reasons)
    assert "Probation lasts six months." in messages
    assert "18 casual leaves" not in messages


# --------------------------------------------------------------------------
# 8. The engine fails at runtime
# --------------------------------------------------------------------------
def test_engine_failure_degrades_instead_of_crashing(evidence_engine):
    """A broken engine must never raise into the evaluator or inflate the score."""

    class BrokenEngine:
        def evaluate(self, **kwargs):
            raise RuntimeError("NLI model unavailable")

    stubs = [s for s in default_signals() if s.name in {"freshness", "ambiguity"}]
    evaluator = Evaluator(
        [*evidence_intelligence_signals(engine=BrokenEngine()), *stubs]
    )

    response = evaluate(
        evaluator,
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=[{"text": "Employees are entitled to 18 casual leaves.", "date": TODAY}],
    )

    assert response.degraded is True
    assert response.decision is Decision.ABSTAIN
    assert ReasonCode.SIGNAL_UNAVAILABLE in codes(response)
    for value in (
        response.signals.relevance,
        response.signals.entailment,
        response.signals.contradiction,
        response.signals.completeness,
    ):
        assert value is None


# --------------------------------------------------------------------------
# 9. The same query under different risk profiles
# --------------------------------------------------------------------------
def test_a_stricter_profile_gives_a_more_conservative_decision(evaluator):
    """The §8.3 demo moment: identical input, different profile, safer answer."""
    case = dict(
        query="What are the leave and probation rules?",
        answer=(
            "Employees receive 18 casual leaves per year. "
            "Probation lasts six months."
        ),
        evidence=[
            {
                "text": "Employees are entitled to 18 casual leaves per year.",
                "source": "policy_2026.pdf",
                "date": TODAY,
            }
        ],
    )

    severity = {
        Decision.ANSWER: 0,
        Decision.CAVEAT: 1,
        Decision.ESCALATE: 2,
        Decision.ABSTAIN: 3,
    }

    lenient = evaluate(evaluator, **case, profile="lenient")
    standard = evaluate(evaluator, **case, profile="standard")
    strict = evaluate(evaluator, **case, profile="strict")

    # Same measurements in all three; only the policy differs.
    assert lenient.answerability_score == standard.answerability_score
    assert standard.answerability_score == strict.answerability_score
    assert standard.signals == strict.signals

    assert severity[strict.decision] > severity[standard.decision]
    assert severity[standard.decision] >= severity[lenient.decision]


def test_an_unknown_profile_is_rejected(evaluator):
    from app.core.config import UnknownProfileError

    with pytest.raises(UnknownProfileError):
        evaluate(
            evaluator,
            query="How many casual leaves?",
            answer="Eighteen.",
            evidence=[{"text": "Employees get 18 casual leaves.", "date": TODAY}],
            profile="paranoid",
        )


# --------------------------------------------------------------------------
# The engine is actually the thing being invoked
# --------------------------------------------------------------------------
def test_the_live_registry_wires_the_real_engine():
    """Guards against the four signals silently reverting to stubs."""
    by_name = {s.name: s for s in default_signals()}

    for name in ("relevance", "entailment", "contradiction", "completeness"):
        assert "aegis_core" in type(by_name[name]).__module__ or hasattr(
            by_name[name], "intelligence"
        ), f"{name} is not backed by the Evidence Intelligence Engine"
        assert not by_name[name].run("q", "a", []).details.get("stub")


def test_one_request_costs_one_engine_call(evaluator, evidence_engine):
    """Four signals must share a single engine pass, not run it four times."""
    calls = []
    original = evidence_engine.evaluate

    def counted(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    evidence_engine.evaluate = counted
    try:
        evaluate(
            evaluator,
            query="How many casual leaves can an employee take?",
            answer="Employees receive 18 casual leaves per year.",
            evidence=[
                {
                    "text": "Employees are entitled to 18 casual leaves per year.",
                    "source": "policy.pdf",
                    "date": TODAY,
                }
            ],
        )
    finally:
        evidence_engine.evaluate = original

    assert len(calls) == 1
