import logging
import time
import uuid
from typing import Any

from app.core.claims import ClaimExtractor
from app.core.config import PolicyConfig, load_policy_config
from app.core.policy import decide
from app.core.scoring import compute_score
from app.evidence.base import Signal
from app.graph.sink import GraphSink, safe_write_trace
from app.graph.templates import render_headline
from app.graph.trace_builder import build_trace
from app.schemas import (
    ClaimResult,
    ClaimStatus,
    Decision,
    EvaluateRequest,
    EvaluateResponse,
    Reason,
    ReasonCode,
    RecommendedAction,
    Signals,
)

logger = logging.getLogger(__name__)


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


class Evaluator:
    """Runs the full Aegis pipeline: signals -> score -> policy -> trace -> response."""

    def __init__(
        self,
        signals: list[Signal],
        config: PolicyConfig | None = None,
        graph_sink: GraphSink | None = None,
        claim_extractor: ClaimExtractor | None = None,
    ):
        names = [s.name for s in signals]
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate signal names: {names}")
        unknown = set(names) - set(Signals.model_fields)
        if unknown:
            raise ValueError(f"Unknown signal names: {sorted(unknown)}")

        self.signals = signals
        self.config = config if config is not None else load_policy_config()
        self.graph_sink = graph_sink
        self.claim_extractor = claim_extractor

    def evaluate(self, request: EvaluateRequest) -> EvaluateResponse:
        start = time.perf_counter()
        request_id = uuid.uuid4().hex
        profile = self.config.get_profile(request.profile)

        # Rule from the plan: no evidence -> ABSTAIN, without calling any model.
        if not request.evidence:
            return self._no_evidence_response(request_id, request, start)

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

        # 3. Extract / collect claims
        claims_list = self._collect_claims(results, request.answer)

        # 4. Build decision-graph trace & write to sink (never blocks decision)
        trace = None
        try:
            entailment_details = (
                results["entailment"].details if "entailment" in results else None
            )
            contradiction_details = (
                results["contradiction"].details if "contradiction" in results else None
            )
            evidence_payload = [e.model_dump() for e in request.evidence]
            reasons_payload = [
                {"code": r.code.value, "message": r.message} for r in outcome.reasons
            ]

            trace = build_trace(
                request_id=request_id,
                decision=outcome.decision.value,
                headline=render_headline(outcome.decision),
                evidence=evidence_payload,
                entailment_details=entailment_details,
                contradiction_details=contradiction_details,
                reasons=reasons_payload,
                answerability_score=score_result.score,
                policy_version=self.config.version,
                profile=request.profile,
            )
            safe_write_trace(self.graph_sink, trace)
        except Exception:
            logger.exception("Failed to build or write decision trace for %s", request_id)

        # 5. Package everything.
        return EvaluateResponse(
            request_id=request_id,
            decision=outcome.decision,
            answerability_score=score_result.score,
            signals=signals,
            reasons=outcome.reasons,
            claims=claims_list,
            caveat_text=outcome.caveat_text,
            clarifying_question=outcome.clarifying_question,
            recommended_action=outcome.recommended_action,
            degraded=bool(score_result.unavailable),
            policy_version=self.config.version,
            latency_ms=_elapsed_ms(start),
            trace=trace,
        )

    def _collect_claims(
        self, results: dict[str, Any], answer: str
    ) -> list[ClaimResult]:
        claims_list: list[ClaimResult] = []
        if "entailment" in results:
            raw_claims = results["entailment"].details.get("claims") or []
            for c in raw_claims:
                if isinstance(c, dict):
                    status_raw = c.get("status")
                    try:
                        status = ClaimStatus(status_raw) if status_raw else ClaimStatus.UNSUPPORTED
                    except ValueError:
                        status = ClaimStatus.UNSUPPORTED

                    support = float(c.get("support", c.get("score", 0.0)))
                    support = max(0.0, min(1.0, support))
                    indices = c.get("evidence_indices") or []

                    claims_list.append(
                        ClaimResult(
                            claim=c.get("claim", ""),
                            status=status,
                            support=support,
                            evidence_indices=list(indices),
                        )
                    )

        if not claims_list and self.claim_extractor is not None and answer:
            extraction = self.claim_extractor.extract(answer)
            for claim_text in extraction.claims:
                claims_list.append(
                    ClaimResult(
                        claim=claim_text,
                        status=ClaimStatus.UNSUPPORTED,
                        support=0.0,
                        evidence_indices=[],
                    )
                )

        return claims_list

    def _no_evidence_response(
        self, request_id: str, request: EvaluateRequest, start: float
    ) -> EvaluateResponse:
        reasons = [
            Reason(
                code=ReasonCode.NO_EVIDENCE,
                message="No evidence was provided, so the answer could not be checked.",
            )
        ]
        trace = None
        try:
            trace = build_trace(
                request_id=request_id,
                decision=Decision.ABSTAIN.value,
                headline=render_headline(Decision.ABSTAIN),
                evidence=[],
                reasons=[{"code": r.code.value, "message": r.message} for r in reasons],
                answerability_score=0.0,
                policy_version=self.config.version,
                profile=request.profile,
            )
            safe_write_trace(self.graph_sink, trace)
        except Exception:
            logger.exception("Failed to build trace for empty evidence request %s", request_id)

        return EvaluateResponse(
            request_id=request_id,
            decision=Decision.ABSTAIN,
            answerability_score=0.0,
            signals=Signals(),
            reasons=reasons,
            claims=[],
            recommended_action=RecommendedAction.ABSTAIN,
            policy_version=self.config.version,
            latency_ms=_elapsed_ms(start),
            trace=trace,
        )
