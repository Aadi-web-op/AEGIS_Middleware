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
from app.graph.templates import render_headline, render_summary
from app.graph.trace_builder import build_trace, utc_now_iso
from app.schemas import (
    ClaimResult,
    ClaimStatus,
    Decision,
    EvaluateRequest,
    EvaluateResponse,
    Explanation,
    ExplanationFactor,
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

    def evaluate(
        self, request: EvaluateRequest, *, request_id: str | None = None
    ) -> EvaluateResponse:
        """Evaluate one request.

        `request_id` is a Python-API-only override (seed scripts and tests
        need deterministic ids). Left as None, a fresh uuid is generated.
        """
        start = time.perf_counter()
        request_id = request_id or uuid.uuid4().hex
        profile = self.config.get_profile(request.profile)

        # Rule from the plan: no evidence -> ABSTAIN, without calling any model.
        # Passages that are only whitespace carry nothing to check against,
        # so a request made solely of them is a no-evidence request too.
        if not any(item.text.strip() for item in request.evidence):
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

        # 3. Collect claims first: the policy has claim-level rules. Only
        # claims the entailment check actually verified are judged; claims
        # from the fallback extractor are listed but never used as evidence
        # of anything.
        claims_list, verified_claims = self._collect_claims(results, request.answer)

        outcome = decide(
            signals,
            score_result,
            profile,
            evidence_count=len(request.evidence),
            time_sensitive=request.time_sensitive,
            clarifying_question=question,
            signal_reasons=signal_reasons,
            claims=verified_claims,
        )
        unavailable_signals = self._unavailable_signals(signals)
        explanation = Explanation(
            summary=render_summary(outcome.decision, outcome.decisive_rule, outcome.factors),
            decisive_rule=outcome.decisive_rule,
            factors=outcome.factors,
        )

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
                query=request.query,
                created_at=utc_now_iso(),
                degraded=bool(score_result.unavailable),
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
            headline=render_headline(outcome.decision),
            unavailable_signals=unavailable_signals,
            explanation=explanation,
        )

    @staticmethod
    def _unavailable_signals(signals: Signals) -> list[str]:
        """Names of the signals that returned no value, in schema order."""
        return [name for name in Signals.model_fields if getattr(signals, name) is None]

    @staticmethod
    def _span(answer: str, claim: str) -> list[int] | None:
        """[start, end) of the claim inside the answer, if it appears verbatim."""
        if not claim:
            return None
        start = answer.find(claim)
        if start < 0:
            # An atomic claim is re-punctuated ("... growth."); try without
            # the closing full stop before giving up.
            trimmed = claim.rstrip(".")
            start = answer.find(trimmed) if trimmed else -1
            if start < 0:
                return None
            return [start, start + len(trimmed)]
        return [start, start + len(claim)]

    @staticmethod
    def _claim_reason(c: dict[str, Any], status: ClaimStatus, verified: bool) -> str:
        if not verified:
            return "The support check could not run, so this claim was not verified."
        supporting = c.get("supporting_evidence_indices") or []
        contradicting = c.get("contradicting_evidence_indices") or []
        grounding = c.get("grounding")

        def labels(indices: list[int]) -> str:
            # 1-based labels (E1, E2, ...) to match how evidence is shown to users.
            return ", ".join(f"E{i + 1}" for i in indices)

        if status == ClaimStatus.SUPPORTED:
            text = f"Stated by evidence {labels(supporting)}."
            if contradicting:
                text += f" Evidence {labels(contradicting)} says otherwise, so the sources disagree."
            return text
        if status == ClaimStatus.CONTRADICTED:
            return f"Contradicted by evidence {labels(contradicting)}."
        if isinstance(grounding, (int, float)) and grounding >= 0.5:
            return (
                "No passage clearly states this. The evidence uses "
                f"{round(grounding * 100)}% of the claim's key words, so it "
                "discusses the topic but could not be confirmed."
            )
        return "No evidence passage states this, and the evidence does not mention it."

    def _collect_claims(
        self, results: dict[str, Any], answer: str
    ) -> tuple[list[ClaimResult], list[ClaimResult] | None]:
        """Returns (claims for the response, claims the policy may judge).

        The second value is None when the entailment check did not produce
        a measurement (signal missing, crashed, or its model was unavailable).
        """
        claims_list: list[ClaimResult] = []
        verified = "entailment" in results and results["entailment"].value is not None
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

                    grounding = c.get("grounding")
                    if not isinstance(grounding, (int, float)) or isinstance(grounding, bool):
                        grounding = None
                    else:
                        grounding = max(0.0, min(1.0, float(grounding)))
                    claim_verified = verified and c.get("nli_available") is not False

                    claims_list.append(
                        ClaimResult(
                            claim=c.get("claim", ""),
                            status=status,
                            support=support,
                            evidence_indices=list(indices),
                            supporting_evidence_indices=list(
                                c.get("supporting_evidence_indices") or []
                            ),
                            contradicting_evidence_indices=list(
                                c.get("contradicting_evidence_indices") or []
                            ),
                            reason=self._claim_reason(c, status, claim_verified),
                            span=self._span(answer, c.get("claim", "")),
                            grounding=grounding,
                        )
                    )

        verified_claims = claims_list if (verified and claims_list) else None

        if not claims_list and self.claim_extractor is not None and answer:
            extraction = self.claim_extractor.extract(answer)
            for claim_text in extraction.claims:
                claims_list.append(
                    ClaimResult(
                        claim=claim_text,
                        status=ClaimStatus.UNSUPPORTED,
                        support=0.0,
                        evidence_indices=[],
                        reason="Listed from the answer text; not verified against the evidence.",
                        span=self._span(answer, claim_text),
                    )
                )

        return claims_list, verified_claims

    def _no_evidence_response(
        self, request_id: str, request: EvaluateRequest, start: float
    ) -> EvaluateResponse:
        reasons = [
            Reason(
                code=ReasonCode.NO_EVIDENCE,
                message="No evidence was provided, so the answer could not be checked.",
            )
        ]
        no_evidence_factor = ExplanationFactor(
            signal="evidence_count",
            value=0.0,
            threshold=1.0,
            comparison="below",
            effect=Decision.ABSTAIN,
            message=reasons[0].message,
        )
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
                query=request.query,
                created_at=utc_now_iso(),
                degraded=False,
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
            headline=render_headline(Decision.ABSTAIN),
            # No signal was run, so none is reported as unavailable: the
            # request was refused before any check, which is not a failure.
            unavailable_signals=[],
            explanation=Explanation(
                summary=render_summary(Decision.ABSTAIN, "veto:no_evidence", [no_evidence_factor]),
                decisive_rule="veto:no_evidence",
                factors=[no_evidence_factor],
            ),
        )
