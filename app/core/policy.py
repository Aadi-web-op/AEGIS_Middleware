from pydantic import BaseModel

from app.core.config import ProfileConfig, Thresholds
from app.core.scoring import ScoreResult
from app.schemas import Decision, Reason, ReasonCode, RecommendedAction, Signals

# Severity order from the plan: the higher number is the more cautious decision.
SEVERITY = {
    Decision.ANSWER: 0,
    Decision.CAVEAT: 1,
    Decision.ESCALATE: 2,
    Decision.ABSTAIN: 3,
}

# If these checks break, Aegis can't be trusted to say ANSWER, so we escalate.
CRITICAL_SIGNALS = {"relevance", "entailment", "contradiction"}

_CODE_FOR_SIGNAL = {
    "relevance": ReasonCode.LOW_RELEVANCE,
    "entailment": ReasonCode.UNSUPPORTED_CLAIM,
    "contradiction": ReasonCode.CONTRADICTION,
    "freshness": ReasonCode.STALE_EVIDENCE,
    "completeness": ReasonCode.INCOMPLETE_EVIDENCE,
    "ambiguity": ReasonCode.AMBIGUOUS_QUERY,
}

DEFAULT_CLARIFYING_QUESTION = (
    "Your question could mean more than one thing. Could you add more detail?"
)


class PolicyOutcome(BaseModel):
    decision: Decision
    reasons: list[Reason]
    recommended_action: RecommendedAction
    caveat_text: str | None = None
    clarifying_question: str | None = None


def more_conservative(a: Decision, b: Decision) -> Decision:
    return a if SEVERITY[a] >= SEVERITY[b] else b


def decision_from_score(score: float, t: Thresholds) -> Decision:
    if score >= t.answer:
        return Decision.ANSWER
    if score >= t.caveat:
        return Decision.CAVEAT
    if score >= t.escalate:
        return Decision.ESCALATE
    return Decision.ABSTAIN


def _goodness(signals: Signals) -> dict[str, float]:
    """Every available signal on one scale where higher = better."""
    values = {
        "relevance": signals.relevance,
        "entailment": signals.entailment,
        "contradiction": None if signals.contradiction is None else 1 - signals.contradiction,
        "freshness": signals.freshness,
        "completeness": signals.completeness,
        "ambiguity": None if signals.ambiguity is None else 1 - signals.ambiguity,
    }
    return {name: v for name, v in values.items() if v is not None}


def _weakest_reason(signals: Signals, why: str) -> Reason:
    name, value = min(_goodness(signals).items(), key=lambda item: item[1])
    return Reason(code=_CODE_FOR_SIGNAL[name], message=f"{why} Weakest signal: {name} ({value:.2f}).")


def decide(
    signals: Signals,
    score_result: ScoreResult,
    profile: ProfileConfig,
    evidence_count: int,
    time_sensitive: bool = False,
    clarifying_question: str | None = None,
    signal_reasons: list[Reason] | None = None,
) -> PolicyOutcome:
    v = profile.vetoes

    # 1. What the score alone says.
    decision = decision_from_score(score_result.score, profile.thresholds)

    # 2. Veto rules: each one is a (minimum severity, reason) pair.
    vetoes: list[tuple[Decision, Reason]] = []

    if evidence_count == 0:
        vetoes.append((Decision.ABSTAIN, Reason(
            code=ReasonCode.NO_EVIDENCE, message="No evidence was provided.")))

    ambiguity_fired = False
    if signals.ambiguity is not None and signals.ambiguity >= v.escalate_above_ambiguity:
        ambiguity_fired = True
        vetoes.append((Decision.ESCALATE, Reason(
            code=ReasonCode.AMBIGUOUS_QUERY,
            message=f"The question is ambiguous (ambiguity {signals.ambiguity:.2f}).")))

    if not ambiguity_fired and signals.relevance is not None and signals.relevance < v.abstain_below_relevance:
        vetoes.append((Decision.ABSTAIN, Reason(
            code=ReasonCode.LOW_RELEVANCE,
            message=f"Evidence is barely related to the question (relevance {signals.relevance:.2f}).")))

    if signals.contradiction is not None and signals.contradiction >= v.escalate_above_contradiction:
        vetoes.append((Decision.ESCALATE, Reason(
            code=ReasonCode.CONTRADICTION,
            message=f"The evidence conflicts with the answer or with itself (contradiction {signals.contradiction:.2f}).")))

    if signals.entailment is not None and signals.entailment < v.escalate_below_support:
        vetoes.append((Decision.ESCALATE, Reason(
            code=ReasonCode.UNSUPPORTED_CLAIM,
            message=f"Key claims in the answer are not backed by the evidence (support {signals.entailment:.2f}).")))

    if time_sensitive and signals.freshness is not None and signals.freshness < v.caveat_below_freshness:
        vetoes.append((Decision.CAVEAT, Reason(
            code=ReasonCode.STALE_EVIDENCE,
            message=f"The evidence may be outdated for a time-sensitive question (freshness {signals.freshness:.2f}).")))

    for name in score_result.unavailable:
        floor = Decision.ESCALATE if name in CRITICAL_SIGNALS else Decision.CAVEAT
        vetoes.append((floor, Reason(
            code=ReasonCode.SIGNAL_UNAVAILABLE,
            message=f"The {name} check could not be computed, so it was treated as the worst case.")))

    # 3. The more conservative decision wins.
    reasons: list[Reason] = []
    for floor, reason in vetoes:
        decision = more_conservative(decision, floor)
        reasons.append(reason)

    # 4. Strict profiles: even an ANSWER needs every signal to clear a minimum.
    if decision == Decision.ANSWER and profile.answer_min_signal is not None:
        goodness = _goodness(signals)
        if goodness and min(goodness.values()) < profile.answer_min_signal:
            decision = Decision.CAVEAT
            reasons.append(_weakest_reason(
                signals, f"This profile needs every signal above {profile.answer_min_signal:.2f}."))
    # 4b. Add the detailed reasons that signals supplied (only when not answering).
    if decision != Decision.ANSWER and signal_reasons:
        seen = {r.message for r in reasons}
        for r in signal_reasons:
            if r.message not in seen:
                reasons.append(r)
                seen.add(r.message)
                
    # 5. Never return a non-ANSWER decision without a human-readable reason.
    if decision != Decision.ANSWER and not reasons:
        reasons.append(_weakest_reason(
            signals,
            f"Overall answerability score {score_result.score:.2f} is below the "
            f"{profile.thresholds.answer:.2f} needed to answer.",
        ))

    # 6. Turn the decision into an action plus any extra text.
    caveat_text = None
    question = None
    if decision == Decision.ANSWER:
        action = RecommendedAction.RETURN_ANSWER
    elif decision == Decision.CAVEAT:
        action = RecommendedAction.RETURN_WITH_CAVEAT
        caveat_text = "Please verify before relying on this. " + " ".join(r.message for r in reasons)
    elif decision == Decision.ESCALATE:
        if ambiguity_fired:
            action = RecommendedAction.ASK_CLARIFYING_QUESTION
            question = clarifying_question or DEFAULT_CLARIFYING_QUESTION
        else:
            action = RecommendedAction.ESCALATE_TO_HUMAN
    else:
        action = RecommendedAction.ABSTAIN

    return PolicyOutcome(
        decision=decision,
        reasons=reasons,
        recommended_action=action,
        caveat_text=caveat_text,
        clarifying_question=question,
    )
    