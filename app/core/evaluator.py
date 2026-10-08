import time

from app.core.config import PolicyConfig, load_policy_config
from app.core.policy import decide
from app.core.scoring import compute_score
from app.evidence.base import Signal
from app.schemas import (
    Decision,
    EvaluateRequest,
    EvaluateResponse,
    Reason,
    ReasonCode,
    RecommendedAction,
    Signals,
)


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


class Evaluator:
    """Runs the full Aegis pipeline: signals -> score -> policy -> response."""

    def __init__(self, signals: list[Signal], config: PolicyConfig | None = None):
        names = [s.name for s in signals]
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate signal names: {names}")
        unknown = set(names) - set(Signals.model_fields)
        if unknown:
            raise ValueError(f"Unknown signal names: {sorted(unknown)}")

        self.signals = signals
        self.config = config if config is not None else load_policy_config()

    def evaluate(self, request: EvaluateRequest) -> EvaluateResponse:
        start = time.perf_counter()
        profile = self.config.get_profile(request.profile)

        # Rule from the plan: no evidence -> ABSTAIN, without calling any model.
        if not request.evidence:
            return self._no_evidence_response(start)

        # 1. Run every signal through its safe wrapper.
        results = {
            s.name: s.run(request.query, request.answer, request.evidence)
            for s in self.signals
        }
        signals = Signals(**{name: r.value for name, r in results.items()})

        # 2. Score, then policy.
        score_result = compute_score(signals, self.config.weights)

        question = None
        if "ambiguity" in results:
            candidate = results["ambiguity"].details.get("clarifying_question")
            if isinstance(candidate, str) and candidate.strip():
                question = candidate

        signal_reasons = [
            reason
            for result in results.values()
            for reason in result.reasons
            if reason.code != ReasonCode.SIGNAL_UNAVAILABLE
        ]

        outcome = decide(
            signals,
            score_result,
            profile,
            evidence_count=len(request.evidence),
            time_sensitive=request.time_sensitive,
            clarifying_question=question,
            signal_reasons=signal_reasons,
        )

        # 3. Package everything.
        return EvaluateResponse(
            decision=outcome.decision,
            answerability_score=score_result.score,
            signals=signals,
            reasons=outcome.reasons,
            caveat_text=outcome.caveat_text,
            clarifying_question=outcome.clarifying_question,
            recommended_action=outcome.recommended_action,
            degraded=bool(score_result.unavailable),
            policy_version=self.config.version,
            latency_ms=_elapsed_ms(start),
        )

    def _no_evidence_response(self, start: float) -> EvaluateResponse:
        return EvaluateResponse(
            decision=Decision.ABSTAIN,
            answerability_score=0.0,
            signals=Signals(),
            reasons=[Reason(
                code=ReasonCode.NO_EVIDENCE,
                message="No evidence was provided, so the answer could not be checked.",
            )],
            recommended_action=RecommendedAction.ABSTAIN,
            policy_version=self.config.version,
            latency_ms=_elapsed_ms(start),
        )
        