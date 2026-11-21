"""Claim-level policy rules, driven with hand-built signals and claims.

No model, no evaluator: these pin down what `decide()` does with a given set
of verified claims, for all three risk profiles.
"""

import pytest

from app.core.config import ClaimVetoes, ProfileConfig, load_policy_config
from app.core.policy import decide
from app.core.scoring import compute_score
from app.schemas import (
    ClaimResult,
    ClaimStatus,
    Decision,
    ReasonCode,
    RecommendedAction,
    Signals,
)

CONFIG = load_policy_config()
PROFILES = ["lenient", "standard", "strict"]


def good(**overrides) -> Signals:
    base = dict(relevance=1, entailment=1, contradiction=0,
                freshness=1, completeness=1, ambiguity=0)
    base.update(overrides)
    return Signals(**base)


def claim(status: str, grounding: float | None = 1.0, text: str | None = None) -> ClaimResult:
    return ClaimResult(
        claim=text or f"A {status.lower()} statement.",
        status=ClaimStatus(status),
        support=0.95 if status == "SUPPORTED" else 0.3,
        grounding=grounding,
    )


def S():
    return claim("SUPPORTED")


def U_ABSENT():
    """Unsupported, and the evidence does not mention it."""
    return claim("UNSUPPORTED", 0.1)


def U_NEAR():
    """Unsupported, but the evidence discusses it."""
    return claim("UNSUPPORTED", 0.8)


def C():
    return claim("CONTRADICTED", 0.9)


def run(claims, profile="standard", signals=None, **kwargs):
    signals = signals or good()
    return decide(signals, compute_score(signals, CONFIG.weights),
                  CONFIG.get_profile(profile), evidence_count=2, claims=claims, **kwargs)


# ---------------------------------------------------------------- fully supported
@pytest.mark.parametrize("profile", PROFILES)
def test_all_claims_supported_is_answered(profile):
    out = run([S(), S(), S()], profile)
    assert out.decision == Decision.ANSWER
    assert out.reasons == []
    assert out.decisive_rule == "score_threshold"


# ---------------------------------------------------------------- one unsupported claim
@pytest.mark.parametrize(
    "profile, expected",
    [("lenient", Decision.CAVEAT), ("standard", Decision.CAVEAT), ("strict", Decision.ESCALATE)],
)
def test_one_unsupported_claim_is_never_answered(profile, expected):
    """The bug this suite exists for: perfect aggregate signals, one invented claim."""
    out = run([S(), S(), S(), U_ABSENT()], profile)
    assert out.decision == expected
    assert out.decisive_rule == "veto:unsupported_claim"
    assert any(r.code == ReasonCode.UNSUPPORTED_CLAIM for r in out.reasons)


def test_unsupported_claim_reason_names_the_claim():
    out = run([S(), claim("UNSUPPORTED", 0.0, "Exercise prevents all diseases.")])
    assert any("Exercise prevents all diseases." in r.message for r in out.reasons)
    assert "Exercise prevents all diseases." in out.caveat_text
    assert out.recommended_action == RecommendedAction.RETURN_WITH_CAVEAT


def test_grounded_unsupported_claim_says_it_could_not_be_confirmed():
    out = run([S(), U_NEAR()])
    assert out.decision == Decision.CAVEAT
    assert any("could not be confirmed" in r.message for r in out.reasons)


# ---------------------------------------------------------------- contradicted claim
@pytest.mark.parametrize("profile", PROFILES)
def test_a_contradicted_claim_escalates_in_every_profile(profile):
    out = run([S(), S(), C()], profile)
    assert out.decision == Decision.ESCALATE
    assert out.decisive_rule == "veto:contradicted_claim"
    assert out.recommended_action == RecommendedAction.ESCALATE_TO_HUMAN
    assert any(r.code == ReasonCode.CONTRADICTION for r in out.reasons)


def test_contradiction_outranks_unsupported():
    out = run([U_ABSENT(), C()])
    assert out.decision == Decision.ESCALATE  # not ABSTAIN: there is a conflict to resolve


# ---------------------------------------------------------------- nothing supported
@pytest.mark.parametrize("profile", PROFILES)
def test_no_supported_and_nothing_mentioned_abstains(profile):
    out = run([U_ABSENT(), U_ABSENT()], profile)
    assert out.decision == Decision.ABSTAIN
    assert out.decisive_rule == "veto:no_supported_claim"
    assert out.recommended_action == RecommendedAction.ABSTAIN


@pytest.mark.parametrize(
    "profile, expected",
    [("lenient", Decision.CAVEAT), ("standard", Decision.CAVEAT), ("strict", Decision.ESCALATE)],
)
def test_no_supported_but_evidence_discusses_it_does_not_abstain(profile, expected):
    """Evidence on the topic, model unsure: warn (or escalate), do not claim silence."""
    out = run([U_NEAR()], profile)
    assert out.decision == expected


def test_abstain_rule_can_be_switched_off():
    profile = CONFIG.get_profile("standard").model_copy(
        update={"claims": ClaimVetoes(abstain_when_none_supported=False)})
    signals = good()
    out = decide(signals, compute_score(signals, CONFIG.weights), profile, 2, claims=[U_ABSENT()])
    assert out.decision == Decision.CAVEAT


# ---------------------------------------------------------------- mostly invented
@pytest.mark.parametrize(
    "claims, profile, expected",
    [
        # 2 of 4 absent
        ([S, S, U_ABSENT, U_ABSENT], "lenient", Decision.CAVEAT),
        ([S, S, U_ABSENT, U_ABSENT], "standard", Decision.CAVEAT),
        ([S, S, U_ABSENT, U_ABSENT], "strict", Decision.ESCALATE),
        # 3 of 4 absent
        ([S, U_ABSENT, U_ABSENT, U_ABSENT], "lenient", Decision.CAVEAT),
        ([S, U_ABSENT, U_ABSENT, U_ABSENT], "standard", Decision.ESCALATE),
        ([S, U_ABSENT, U_ABSENT, U_ABSENT], "strict", Decision.ESCALATE),
        # 3 of 4 unsupported, but the evidence discusses them
        ([S, U_NEAR, U_NEAR, U_NEAR], "standard", Decision.CAVEAT),
    ],
)
def test_share_of_invented_claims(claims, profile, expected):
    out = run([make() for make in claims], profile)
    assert out.decision == expected


def test_standard_names_the_ungrounded_rule():
    out = run([S(), U_ABSENT(), U_ABSENT(), U_ABSENT()])
    assert out.decisive_rule == "veto:ungrounded_claims"
    assert any("3 of 4 claims" in r.message for r in out.reasons)


# ---------------------------------------------------------------- interaction with other rules
def test_ambiguous_question_asks_instead_of_abstaining():
    out = run([U_ABSENT()], signals=good(ambiguity=0.9))
    assert out.decision == Decision.ESCALATE
    assert out.recommended_action == RecommendedAction.ASK_CLARIFYING_QUESTION


def test_irrelevant_evidence_still_abstains_with_supported_claims():
    out = run([S()], signals=good(relevance=0.05))
    assert out.decision == Decision.ABSTAIN
    assert out.decisive_rule == "veto:low_relevance"


def test_claims_are_ignored_when_the_support_check_did_not_run():
    """Unverified claims must not be read as 'unsupported'."""
    out = run([U_ABSENT()], signals=good(entailment=None))
    assert out.decision == Decision.ESCALATE  # critical signal missing
    assert out.decisive_rule == "veto:signal_unavailable:entailment"
    assert all(r.code != ReasonCode.UNSUPPORTED_CLAIM for r in out.reasons)


def test_unmeasured_grounding_counts_as_not_grounded():
    out = run([claim("UNSUPPORTED", None)])
    assert out.decision == Decision.ABSTAIN


@pytest.mark.parametrize("claims", [None, []])
def test_without_claims_behaviour_is_the_old_behaviour(claims):
    assert run(claims).decision == Decision.ANSWER
    low = run(claims, signals=good(entailment=0.2))
    assert low.decision == Decision.ESCALATE
    assert low.decisive_rule == "veto:low_support"


# ---------------------------------------------------------------- unavailable signals
@pytest.mark.parametrize("name", ["freshness", "completeness", "ambiguity"])
def test_unavailable_minor_signal_caveats(name):
    out = run([S()], signals=good(**{name: None}), time_sensitive=True)
    assert out.decision == Decision.CAVEAT
    assert out.decisive_rule == f"veto:signal_unavailable:{name}"
    assert any(r.code == ReasonCode.SIGNAL_UNAVAILABLE for r in out.reasons)


def test_undated_evidence_does_not_caveat_a_timeless_question():
    out = run([S()], signals=good(freshness=None), time_sensitive=False)
    assert out.decision == Decision.ANSWER
    assert all(r.code != ReasonCode.SIGNAL_UNAVAILABLE for r in out.reasons)


@pytest.mark.parametrize("name", ["relevance", "entailment", "contradiction"])
def test_unavailable_critical_signal_escalates(name):
    out = run([S()], signals=good(**{name: None}))
    assert out.decision == Decision.ESCALATE
    assert out.recommended_action == RecommendedAction.ESCALATE_TO_HUMAN


def test_all_signals_unavailable_fails_closed():
    signals = Signals()
    out = decide(signals, compute_score(signals, CONFIG.weights),
                 CONFIG.get_profile("standard"), 2, claims=None, time_sensitive=True)
    assert out.decision == Decision.ABSTAIN  # score 0
    assert len([f for f in out.factors if f.comparison == "unavailable"]) == 6


# ---------------------------------------------------------------- explanation factors
def test_factors_always_start_with_the_score():
    out = run([S()])
    assert out.factors[0].signal == "answerability_score"
    assert out.factors[0].effect == Decision.ANSWER


def test_every_veto_has_a_factor_with_value_and_threshold():
    out = run(None, signals=good(contradiction=0.9, freshness=0.1), time_sensitive=True)
    by_signal = {f.signal: f for f in out.factors}
    assert by_signal["contradiction"].value == 0.9
    assert by_signal["contradiction"].threshold == 0.60
    assert by_signal["contradiction"].effect == Decision.ESCALATE
    assert by_signal["freshness"].comparison == "below"
    assert by_signal["freshness"].effect == Decision.CAVEAT
    assert out.decisive_rule == "veto:contradiction"


def test_score_threshold_is_decisive_when_no_veto_is_stricter():
    out = run(None, signals=good(relevance=0.4, entailment=0.45, completeness=0.3))
    assert out.decision == Decision.CAVEAT
    assert out.decisive_rule == "score_threshold"


def test_strict_minimum_signal_rule_is_named():
    out = run([S()], profile="strict", signals=good(completeness=0.55))
    assert out.decision == Decision.CAVEAT
    assert out.decisive_rule == "answer_min_signal"


def test_duplicate_reason_messages_are_not_repeated():
    same = claim("UNSUPPORTED", 0.0, "Same claim.")
    out = run([S(), same, same.model_copy()])
    messages = [r.message for r in out.reasons]
    assert len(messages) == len(set(messages))


# ---------------------------------------------------------------- configuration
def test_every_profile_declares_claim_rules():
    for name in PROFILES:
        cfg = CONFIG.get_profile(name).claims
        assert cfg.contradicted_floor == Decision.ESCALATE
        assert 0.0 < cfg.min_grounding <= 1.0
    assert CONFIG.get_profile("strict").claims.unsupported_floor == Decision.ESCALATE


def test_profile_without_a_claims_block_still_loads():
    profile = ProfileConfig.model_validate({
        "thresholds": {"answer": 0.8, "caveat": 0.6, "escalate": 0.4},
        "vetoes": {"abstain_below_relevance": 0.3, "escalate_above_contradiction": 0.6,
                   "escalate_below_support": 0.4, "caveat_below_freshness": 0.4,
                   "escalate_above_ambiguity": 0.3},
    })
    assert profile.claims.unsupported_floor == Decision.CAVEAT
