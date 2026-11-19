"""Explain escalations by replaying the configured score and decision policy."""

from math import ceil, floor

from app.core.config import PolicyConfig
from app.core.policy import decide, decision_from_score
from app.core.scoring import compute_score
from app.schemas import (
    Decision, EvaluateRequest, EvaluateResponse, PolicyExplanation, SignalChange,
)

_RESOLUTION = 10_000
_LOWER_IS_BETTER = {"ambiguity", "contradiction"}
_CAN_RETURN = {Decision.ANSWER, Decision.CAVEAT}


def explain_escalation(
    request: EvaluateRequest, response: EvaluateResponse, config: PolicyConfig
) -> PolicyExplanation | None:
    if response.decision != Decision.ESCALATE:
        return None

    profile = config.get_profile(request.profile)
    signals = response.signals
    score = compute_score(signals, config.weights)
    context = {"evidence_count": len(request.evidence), "time_sensitive": request.time_sensitive}
    baseline = decide(signals, score, profile, **context)
    if baseline.decision != response.decision:
        return None
    candidates = []

    for name, current in signals.model_dump().items():
        if current is None:
            continue
        # Search in terms of signal quality, so higher means better in every case.
        inverted = name in _LOWER_IS_BETTER
        scaled = current * _RESOLUTION
        first = _RESOLUTION - ceil(scaled) + 1 if inverted else floor(scaled) + 1
        if first > _RESOLUTION:
            continue

        def replay(quality: int):
            target = (_RESOLUTION - quality if inverted else quality) / _RESOLUTION
            updated = signals.model_copy(update={name: target})
            new_score = compute_score(updated, config.weights)
            outcome = decide(updated, new_score, profile, **context)
            return target, new_score.score, outcome.decision

        # Once an improvement permits returning the answer, further improvement on
        # the same signal preserves that. If removing ambiguity exposes a relevance
        # veto, ambiguity alone cannot permit a return at all.
        last = _RESOLUTION
        if replay(last)[2] not in _CAN_RETURN:
            continue
        while first < last:
            middle = (first + last) // 2
            if replay(middle)[2] in _CAN_RETURN:
                last = middle
            else:
                first = middle + 1

        target, new_score, decision = replay(first)
        action = "Lower" if inverted else "Raise"
        candidates.append(SignalChange(
            signal=name,
            current=current,
            target=target,
            delta=round(target - current, 12),
            resulting_decision=decision,
            resulting_score=new_score,
            hint=f"{action} {name} to {target:.4f} for {decision.value} under the {request.profile} profile.",
        ))

    return PolicyExplanation(
        score_only_decision=decision_from_score(score.score, profile.thresholds),
        policy_reasons=baseline.reasons,
        contributions=score.contributions,
        unavailable_signals=score.unavailable,
        minimum_change=min(candidates, key=lambda change: abs(change.delta), default=None),
    )
