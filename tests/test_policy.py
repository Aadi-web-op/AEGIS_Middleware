import pytest
from pydantic import ValidationError

from app.core.config import PolicyConfig, Thresholds, UnknownProfileError, load_policy_config
from app.core.policy import decide, more_conservative
from app.core.scoring import compute_score
from app.schemas import Decision, ReasonCode, RecommendedAction, Signals, Reason

CONFIG = load_policy_config()


def make_signals(**overrides) -> Signals:
    base = dict(relevance=1, entailment=1, contradiction=0,
                freshness=1, completeness=1, ambiguity=0)
    base.update(overrides)
    return Signals(**base)


def run(signals: Signals, profile="standard", evidence_count=3, **kwargs):
    return decide(signals, compute_score(signals, CONFIG.weights),
                  CONFIG.get_profile(profile), evidence_count, **kwargs)


def test_clean_signals_give_answer():
    out = run(make_signals())
    assert out.decision == Decision.ANSWER
    assert out.recommended_action == RecommendedAction.RETURN_ANSWER
    assert out.reasons == []


def test_veto_catches_contradiction_the_average_hides():
    s = make_signals(relevance=0.95, entailment=0.95, contradiction=0.9,
                     freshness=0.9, completeness=0.9, ambiguity=0.05)
    assert compute_score(s).score == pytest.approx(0.81)  # score alone says ANSWER
    out = run(s)
    assert out.decision == Decision.ESCALATE
    assert out.reasons[0].code == ReasonCode.CONTRADICTION


def test_no_evidence_abstains_even_with_perfect_signals():
    out = run(make_signals(), evidence_count=0)
    assert out.decision == Decision.ABSTAIN
    assert out.reasons[0].code == ReasonCode.NO_EVIDENCE


def test_irrelevant_evidence_abstains():
    out = run(make_signals(relevance=0.2))
    assert out.decision == Decision.ABSTAIN


def test_stale_evidence_only_matters_when_time_sensitive():
    s = make_signals(freshness=0.3)
    assert run(s, time_sensitive=False).decision == Decision.ANSWER
    out = run(s, time_sensitive=True)
    assert out.decision == Decision.CAVEAT
    assert out.reasons[0].code == ReasonCode.STALE_EVIDENCE
    assert out.caveat_text is not None


def test_ambiguity_escalates_with_clarifying_question():
    out = run(make_signals(ambiguity=0.7))
    assert out.decision == Decision.ESCALATE
    assert out.recommended_action == RecommendedAction.ASK_CLARIFYING_QUESTION
    assert out.clarifying_question


def test_custom_clarifying_question_is_used():
    out = run(make_signals(ambiguity=0.7), clarifying_question="Which leave type?")
    assert out.clarifying_question == "Which leave type?"


def test_unsupported_answer_escalates():
    out = run(make_signals(entailment=0.3))
    assert out.decision == Decision.ESCALATE
    assert out.recommended_action == RecommendedAction.ESCALATE_TO_HUMAN


def test_missing_critical_signal_escalates():
    out = run(make_signals(contradiction=None))
    assert out.decision == Decision.ESCALATE
    assert out.reasons[0].code == ReasonCode.SIGNAL_UNAVAILABLE


def test_missing_minor_signal_only_adds_caveat():
    out = run(make_signals(freshness=None))
    assert out.decision == Decision.CAVEAT


def test_low_score_without_veto_still_explains_itself():
    s = make_signals(relevance=0.5, entailment=0.5, contradiction=0.5,
                     freshness=0.5, completeness=0.5, ambiguity=0.5)
    out = run(s)
    assert out.decision == Decision.ESCALATE
    assert len(out.reasons) >= 1


def test_same_question_standard_vs_strict():
    s = make_signals(relevance=0.9, entailment=0.9, contradiction=0.1,
                     freshness=0.8, completeness=0.8, ambiguity=0.1)
    assert run(s, "standard").decision == Decision.ANSWER
    assert run(s, "strict").decision == Decision.CAVEAT


def test_strict_needs_every_signal_above_minimum():
    s = make_signals(freshness=0.5)
    assert compute_score(s).score >= 0.90  # score is high enough...
    out = run(s, "strict")                 # ...but one signal is weak
    assert out.decision == Decision.CAVEAT
    assert out.reasons[0].code == ReasonCode.STALE_EVIDENCE


def test_more_conservative_picks_the_stricter():
    assert more_conservative(Decision.ANSWER, Decision.ESCALATE) == Decision.ESCALATE
    assert more_conservative(Decision.ABSTAIN, Decision.CAVEAT) == Decision.ABSTAIN


def test_default_config_has_three_profiles():
    assert set(CONFIG.profiles) == {"lenient", "standard", "strict"}


def test_unknown_profile_raises_clear_error():
    with pytest.raises(UnknownProfileError):
        CONFIG.get_profile("paranoid")


def test_unordered_thresholds_are_rejected():
    with pytest.raises(ValidationError):
        Thresholds(answer=0.5, caveat=0.8, escalate=0.4)

def test_signal_supplied_reasons_are_added_when_not_answering():
    extra = [Reason(code=ReasonCode.CONTRADICTION, message="Two sources disagree on the leave count.")]
    out = run(make_signals(contradiction=0.9), signal_reasons=extra)
    assert any(r.message == "Two sources disagree on the leave count." for r in out.reasons)


def test_signal_supplied_reasons_are_ignored_when_answering():
    extra = [Reason(code=ReasonCode.CONTRADICTION, message="Minor note.")]
    assert run(make_signals(), signal_reasons=extra).reasons == []