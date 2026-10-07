import pytest
from pydantic import ValidationError

from app.core.scoring import ScoringWeights, compute_score
from app.schemas import Signals


def test_perfect_signals_score_one():
    s = Signals(relevance=1, entailment=1, contradiction=0,
                freshness=1, completeness=1, ambiguity=0)
    assert compute_score(s).score == pytest.approx(1.0)


def test_plan_example_signals():
    # 0.25*0.94 + 0.25*0.95 + 0.15*0.98 + 0.10*0.90 + 0.15*0.91 + 0.10*0.96
    s = Signals(relevance=0.94, entailment=0.95, contradiction=0.02,
                freshness=0.90, completeness=0.91, ambiguity=0.04)
    assert compute_score(s).score == pytest.approx(0.942)


def test_average_alone_lets_a_contradiction_through():
    # Why veto rules exist: a direct contradiction (0.9) still scores 0.81,
    # which is above the 0.80 ANSWER threshold.
    s = Signals(relevance=0.95, entailment=0.95, contradiction=0.9,
                freshness=0.9, completeness=0.9, ambiguity=0.05)
    assert compute_score(s).score == pytest.approx(0.81)


def test_missing_signal_counts_as_worst_case():
    # Contradiction unknown -> agreement term contributes 0 -> 1.0 - 0.15 = 0.85
    s = Signals(relevance=1, entailment=1, contradiction=None,
                freshness=1, completeness=1, ambiguity=0)
    result = compute_score(s)
    assert result.score == pytest.approx(0.85)
    assert result.unavailable == ["contradiction"]


def test_all_signals_missing_scores_zero():
    result = compute_score(Signals())
    assert result.score == 0.0
    assert len(result.unavailable) == 6


def test_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        ScoringWeights(relevance=0.9)


def test_contributions_add_up_to_score():
    s = Signals(relevance=0.8, entailment=0.7, contradiction=0.1,
                freshness=0.6, completeness=0.9, ambiguity=0.2)
    result = compute_score(s)
    assert sum(result.contributions.values()) == pytest.approx(result.score, abs=1e-3)
    