from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.core.config import ProfileConfig, Thresholds
from app.core.scoring import ScoreResult
from app.schemas import (
    ClaimResult,
    ClaimStatus,
    Decision,
    ExplanationFactor,
    Reason,
    ReasonCode,
    RecommendedAction,
    Signals,
)

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
    # Which rule set the final decision ("score_threshold", "veto:<name>",
    # "answer_min_signal"), and every measured value that was compared.
    decisive_rule: str | None = None
    factors: list[ExplanationFactor] = Field(default_factory=list)


@dataclass
class _Veto:
    floor: Decision
    reason: Reason
    rule: str
    factor: ExplanationFactor


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _claim_vetoes(
    claims: list[ClaimResult], profile: ProfileConfig, allow_abstain: bool
) -> list[_Veto]:
    """Rules that look at individual claims instead of the average.

    The aggregate support score hides a single invented statement inside an
    otherwise well-supported answer. These rules cannot be averaged away.
    """
    cfg = profile.claims
    total = len(claims)
    if total == 0:
        return []

    def grounded(c: ClaimResult) -> bool:
        return c.grounding is not None and c.grounding >= cfg.min_grounding

    contradicted = [c for c in claims if c.status == ClaimStatus.CONTRADICTED]
    unsupported = [c for c in claims if c.status == ClaimStatus.UNSUPPORTED]
    supported = [c for c in claims if c.status == ClaimStatus.SUPPORTED]
    ungrounded = [c for c in unsupported if not grounded(c)]
    out: list[_Veto] = []

    for c in contradicted:
        message = f'The claim "{_short(c.claim)}" is contradicted by the evidence.'
        out.append(_Veto(
            cfg.contradicted_floor,
            Reason(code=ReasonCode.CONTRADICTION, message=message),
            "veto:contradicted_claim",
            ExplanationFactor(
                signal="claims", value=round(len(contradicted) / total, 4), threshold=0.0,
                comparison="above", effect=cfg.contradicted_floor, message=message),
        ))

    if (
        allow_abstain
        and cfg.abstain_when_none_supported
        and not supported
        and not contradicted
        and len(ungrounded) == total
    ):
        message = (
            f"None of the {total} claim(s) in the answer is supported by the evidence, "
            "and the evidence does not mention what they state."
        )
        out.append(_Veto(
            Decision.ABSTAIN,
            Reason(code=ReasonCode.UNSUPPORTED_CLAIM, message=message),
            "veto:no_supported_claim",
            ExplanationFactor(
                signal="claims", value=0.0, threshold=None,
                comparison="none_supported", effect=Decision.ABSTAIN, message=message),
        ))
    elif (
        cfg.escalate_at_ungrounded_fraction is not None
        and ungrounded
        and len(ungrounded) / total >= cfg.escalate_at_ungrounded_fraction
    ):
        share = len(ungrounded) / total
        message = (
            f"{len(ungrounded)} of {total} claims in the answer are not mentioned "
            "in the evidence at all."
        )
        out.append(_Veto(
            Decision.ESCALATE,
            Reason(code=ReasonCode.UNSUPPORTED_CLAIM, message=message),
            "veto:ungrounded_claims",
            ExplanationFactor(
                signal="claims", value=round(share, 4),
                threshold=cfg.escalate_at_ungrounded_fraction,
                comparison="at_or_above", effect=Decision.ESCALATE, message=message),
        ))

    for c in unsupported:
        if grounded(c):
            message = (
                f'The claim "{_short(c.claim)}" could not be confirmed: the evidence '
                "discusses it but does not clearly state it."
            )
        else:
            message = f'The claim "{_short(c.claim)}" is not backed by the evidence.'
        out.append(_Veto(
            cfg.unsupported_floor,
            Reason(code=ReasonCode.UNSUPPORTED_CLAIM, message=message),
            "veto:unsupported_claim",
            ExplanationFactor(
                signal="claims", value=round(len(unsupported) / total, 4), threshold=0.0,
                comparison="above", effect=cfg.unsupported_floor, message=message),
        ))
    return out


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


def _score_factor(score: float, t: Thresholds, decision: Decision) -> ExplanationFactor:
    if decision == Decision.ANSWER:
        threshold, comparison = t.answer, "at_or_above"
        message = f"Overall answerability score {score:.2f} meets the {t.answer:.2f} needed to answer."
    else:
        threshold, comparison = t.answer, "below"
        message = (
            f"Overall answerability score {score:.2f} is below the "
            f"{t.answer:.2f} needed to answer."
        )
    return ExplanationFactor(
        signal="answerability_score", value=round(score, 4), threshold=threshold,
        comparison=comparison, effect=decision, message=message,
    )


def decide(
    signals: Signals,
    score_result: ScoreResult,
    profile: ProfileConfig,
    evidence_count: int,
    time_sensitive: bool = False,
    clarifying_question: str | None = None,
    signal_reasons: list[Reason] | None = None,
    claims: list[ClaimResult] | None = None,
) -> PolicyOutcome:
    """Turn signals (and, when given, verified claims) into a decision.

    `claims` must contain only claims that were actually verified against the
    evidence. Passing None (or nothing) skips the claim-level rules, which is
    exactly the pre-claim behaviour.
    """
    v = profile.vetoes

    # 1. What the score alone says.
    score_decision = decision_from_score(score_result.score, profile.thresholds)
    decision = score_decision
    factors: list[ExplanationFactor] = [
        _score_factor(score_result.score, profile.thresholds, score_decision)
    ]

    # 2. Veto rules: each one is a minimum severity plus its reason.
    vetoes: list[_Veto] = []

    def veto(floor, code, message, rule, signal, value, threshold, comparison):
        vetoes.append(_Veto(
            floor, Reason(code=code, message=message), rule,
            ExplanationFactor(signal=signal, value=value, threshold=threshold,
                              comparison=comparison, effect=floor, message=message),
        ))

    if evidence_count == 0:
        veto(Decision.ABSTAIN, ReasonCode.NO_EVIDENCE, "No evidence was provided.",
             "veto:no_evidence", "evidence_count", 0.0, 1.0, "below")

    ambiguity_fired = False
    if signals.ambiguity is not None and signals.ambiguity >= v.escalate_above_ambiguity:
        ambiguity_fired = True
        veto(Decision.ESCALATE, ReasonCode.AMBIGUOUS_QUERY,
             f"The question is ambiguous (ambiguity {signals.ambiguity:.2f}).",
             "veto:ambiguous_query", "ambiguity", signals.ambiguity,
             v.escalate_above_ambiguity, "at_or_above")

    if not ambiguity_fired and signals.relevance is not None and signals.relevance < v.abstain_below_relevance:
        veto(Decision.ABSTAIN, ReasonCode.LOW_RELEVANCE,
             f"Evidence is barely related to the question (relevance {signals.relevance:.2f}).",
             "veto:low_relevance", "relevance", signals.relevance,
             v.abstain_below_relevance, "below")

    if signals.contradiction is not None and signals.contradiction >= v.escalate_above_contradiction:
        veto(Decision.ESCALATE, ReasonCode.CONTRADICTION,
             f"The evidence conflicts with the answer or with itself (contradiction {signals.contradiction:.2f}).",
             "veto:contradiction", "contradiction", signals.contradiction,
             v.escalate_above_contradiction, "at_or_above")

    if signals.entailment is not None and signals.entailment < v.escalate_below_support:
        veto(Decision.ESCALATE, ReasonCode.UNSUPPORTED_CLAIM,
             f"Key claims in the answer are not backed by the evidence (support {signals.entailment:.2f}).",
             "veto:low_support", "entailment", signals.entailment,
             v.escalate_below_support, "below")

    if time_sensitive and signals.freshness is not None and signals.freshness < v.caveat_below_freshness:
        veto(Decision.CAVEAT, ReasonCode.STALE_EVIDENCE,
             f"The evidence may be outdated for a time-sensitive question (freshness {signals.freshness:.2f}).",
             "veto:stale_evidence", "freshness", signals.freshness,
             v.caveat_below_freshness, "below")

    for name in score_result.unavailable:
        floor = Decision.ESCALATE if name in CRITICAL_SIGNALS else Decision.CAVEAT
        veto(floor, ReasonCode.SIGNAL_UNAVAILABLE,
             f"The {name} check could not be computed, so it was treated as the worst case.",
             f"veto:signal_unavailable:{name}", name, None, None, "unavailable")

    # 2b. Claim-level rules. Skipped when the support check itself did not
    # run: unverified claims say nothing about the evidence.
    if claims and signals.entailment is not None:
        vetoes.extend(_claim_vetoes(claims, profile, allow_abstain=not ambiguity_fired))

    # 3. The more conservative decision wins.
    reasons: list[Reason] = []
    seen_messages: set[str] = set()
    for item in vetoes:
        decision = more_conservative(decision, item.floor)
        if item.reason.message not in seen_messages:
            seen_messages.add(item.reason.message)
            reasons.append(item.reason)
        factors.append(item.factor)

    decisive_rule = "score_threshold"
    if SEVERITY[decision] > SEVERITY[score_decision]:
        decisive_rule = next(i.rule for i in vetoes if i.floor == decision)

    # 4. Strict profiles: even an ANSWER needs every signal to clear a minimum.
    if decision == Decision.ANSWER and profile.answer_min_signal is not None:
        goodness = _goodness(signals)
        if goodness and min(goodness.values()) < profile.answer_min_signal:
            decision = Decision.CAVEAT
            decisive_rule = "answer_min_signal"
            weakest = _weakest_reason(
                signals, f"This profile needs every signal above {profile.answer_min_signal:.2f}.")
            reasons.append(weakest)
            name, value = min(goodness.items(), key=lambda item: item[1])
            factors.append(ExplanationFactor(
                signal=name, value=round(value, 4), threshold=profile.answer_min_signal,
                comparison="below", effect=Decision.CAVEAT, message=weakest.message))

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
        decisive_rule=decisive_rule,
        factors=factors,
    )
