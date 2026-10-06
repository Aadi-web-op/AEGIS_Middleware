"""Entailment/Support Signal - Verifies whether evidence supports claims in the answer.

Pipeline:
  ANSWER -> claim extraction -> claim/evidence pairs -> batched NLI -> aggregate

All (premise=evidence, hypothesis=claim) pairs for the whole evaluation are
collected and run through one batched NLI forward pass, which is the
dominant performance win on CPU (see models/nli.py).
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

from aegis_core.signals.base import BaseSignal, SignalResult, SignalName
from aegis_core.models.nli import NLIRunner
from aegis_core.models.registry import NLI_CANDIDATES

logger = logging.getLogger(__name__)

# Filler prefixes that are not verifiable claims.
_FILLER_PATTERNS = (
    r"^(here is|here are|this is|that is|the answer is|in summary|to summarize)\b",
    r"^(based on|according to|as mentioned|as stated|as per)\b",
    r"^(i think|i believe|it seems|it appears|i can|you can)\b",
)


@dataclass
class ClaimResult:
    """Result of verifying a single claim against the evidence."""
    claim: str
    label: str  # "ENTAILMENT" | "CONTRADICTION" | "NEUTRAL"
    score: float
    evidence: List[str]
    evidence_scores: List[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "label": self.label,
            "score": round(self.score, 4),
            "evidence": self.evidence,
            "evidence_scores": [round(s, 4) for s in self.evidence_scores],
        }


def _is_filler(text: str) -> bool:
    low = text.lower()
    return any(re.match(p, low) for p in _FILLER_PATTERNS)


def extract_claims(answer: str, max_claims: int = 10) -> List[str]:
    """
    Extract verifiable claims from an answer by sentence splitting.

    This is intentionally simple and deterministic. It avoids dependency on
    an LLM or parser so the signal stays fast and auditable on CPU.
    """
    if not answer:
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer.strip())]
    claims = [
        s for s in sentences
        if len(s) > 15 and not _is_filler(s) and any(c.isalpha() for c in s)
    ]
    return claims[:max_claims]


class EntailmentSignal(BaseSignal):
    """Claim-level support verification via batched NLI."""

    def __init__(
        self,
        nli_model_id: str = "cross-encoder/nli-MiniLM2-L6-H768",
        max_claims: int = 10,
        max_evidence_per_claim: int = 5,
        entailment_threshold: float = 0.5,
        contradiction_threshold: float = 0.5,
    ):
        self.nli = NLIRunner(nli_model_id)
        self.max_claims = max_claims
        self.max_evidence_per_claim = max_evidence_per_claim
        self.entailment_threshold = entailment_threshold
        self.contradiction_threshold = contradiction_threshold

    @property
    def signal_name(self) -> SignalName:
        return SignalName.ENTAILMENT

    def evaluate(
        self,
        query: str,
        answer: str,
        evidence: List[str],
        **kwargs
    ) -> SignalResult:
        """
        Evaluate how well the evidence supports the claims in the answer.

        Returns a SignalResult whose value is the aggregate support score in
        [0, 1] and whose details carry per-claim diagnostics.
        """
        if not answer or not answer.strip():
            return self._handle_empty_answer(SignalName.ENTAILMENT, default_value=0.0)

        if not evidence:
            return SignalResult(
                signal=SignalName.ENTAILMENT,
                value=0.0,
                reasons=["No evidence provided to verify claims"],
                details={
                    "support_score": 0.0,
                    "claims": [],
                    "claim_count": 0,
                    "evidence_count": 0,
                    "checkable": False,
                },
            )

        claims = extract_claims(answer, self.max_claims)
        if not claims:
            return SignalResult(
                signal=SignalName.ENTAILMENT,
                value=0.5,
                reasons=["No verifiable claims extracted from answer"],
                details={
                    "support_score": 0.5,
                    "claims": [],
                    "claim_count": 0,
                    "evidence_count": len(evidence),
                    "checkable": False,
                },
            )

        evidence = evidence[: self.max_evidence_per_claim]

        claim_results = self._verify_claims(claims, evidence)
        support_score = self._aggregate_support(claim_results)
        reasons = self._generate_reasons(claim_results, support_score)

        return SignalResult(
            signal=SignalName.ENTAILMENT,
            value=support_score,
            reasons=reasons,
            details={
                "support_score": round(support_score, 4),
                "claims": [cr.to_dict() for cr in claim_results],
                "claim_count": len(claim_results),
                "evidence_count": len(evidence),
                "nli_model": self.nli.model_id,
                "checkable": True,
            },
        )

    # ------------------------------------------------------------------
    def _verify_claims(
        self, claims: List[str], evidence: List[str]
    ) -> List[ClaimResult]:
        """Run one batched NLI pass over all claim/evidence pairs."""
        pairs: List[Tuple[int, int]] = []
        for ci, claim in enumerate(claims):
            for ei, ev in enumerate(evidence):
                pairs.append((ci, ei))

        # premise = evidence, hypothesis = claim
        nli_pairs = [(evidence[ei], claims[ci]) for ci, ei in pairs]

        try:
            preds = self.nli.infer_batch(nli_pairs)
        except Exception as exc:
            logger.warning("NLI inference failed: %s", exc)
            preds = None

        # Organise predictions per claim.
        per_claim: List[List[Optional[Any]]] = [
            [None] * len(evidence) for _ in claims
        ]
        if preds:
            for (ci, ei), pred in zip(pairs, preds):
                per_claim[ci][ei] = pred

        results: List[ClaimResult] = []
        for ci, claim in enumerate(claims):
            results.append(self._resolve_claim(claim, evidence, per_claim[ci]))
        return results

    def _resolve_claim(
        self,
        claim: str,
        evidence: List[str],
        preds: List[Optional[Any]],
    ) -> ClaimResult:
        """Resolve the best label and score for a single claim."""
        best_label = "NEUTRAL"
        best_entailment = 0.0
        best_contradiction = 0.0
        best_neutral = 0.0
        supporting: List[str] = []
        ent_scores: List[float] = []

        for ev, pred in zip(evidence, preds):
            if pred is None:
                ent_scores.append(0.0)
                continue
            ent_scores.append(pred.entailment)

            if pred.entailment > best_entailment:
                best_entailment = pred.entailment
            if pred.contradiction > best_contradiction:
                best_contradiction = pred.contradiction
            if pred.neutral > best_neutral:
                best_neutral = pred.neutral

        # Entailment outranks contradiction; a claim that is both supported
        # and contradicted by different sources is treated as entailed but
        # flagged by the contradiction signal instead.
        if best_entailment >= self.entailment_threshold:
            best_label = "ENTAILMENT"
            supporting = [
                ev for ev, p in zip(evidence, preds)
                if p is not None and p.entailment >= self.entailment_threshold
            ]
            score = best_entailment
        elif best_contradiction >= self.contradiction_threshold:
            best_label = "CONTRADICTION"
            supporting = [
                ev for ev, p in zip(evidence, preds)
                if p is not None and p.contradiction >= self.contradiction_threshold
            ]
            # Contradiction means the answer is unsupported.
            score = 1.0 - best_contradiction
        else:
            best_label = "NEUTRAL"
            score = best_neutral * 0.5

        if not supporting:
            supporting = evidence[:1]

        return ClaimResult(
            claim=claim,
            label=best_label,
            score=round(max(0.0, min(1.0, score)), 4),
            evidence=supporting[:3],
            evidence_scores=ent_scores,
        )

    # ------------------------------------------------------------------
    def _aggregate_support(self, claim_results: List[ClaimResult]) -> float:
        """Weighted aggregate of claim scores in [0, 1]."""
        if not claim_results:
            return 0.5

        total_weight = 0.0
        weighted_sum = 0.0
        for cr in claim_results:
            weight = 1.0 if cr.label in ("ENTAILMENT", "CONTRADICTION") else 0.5
            weighted_sum += cr.score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.5
        return round(max(0.0, min(1.0, weighted_sum / total_weight)), 4)

    def _generate_reasons(
        self, claim_results: List[ClaimResult], support_score: float
    ) -> List[str]:
        reasons: List[str] = []
        total = len(claim_results)
        entailment_count = sum(1 for c in claim_results if c.label == "ENTAILMENT")
        contradiction_count = sum(1 for c in claim_results if c.label == "CONTRADICTION")
        neutral_count = sum(1 for c in claim_results if c.label == "NEUTRAL")

        if support_score >= 0.8:
            reasons.append(f"Strong support: {entailment_count}/{total} claims entailed by evidence")
        elif support_score >= 0.6:
            reasons.append(f"Moderate support: {entailment_count}/{total} entailed, {neutral_count} neutral")
        elif support_score >= 0.4:
            reasons.append(
                f"Partial support: {entailment_count} entailed, {neutral_count} neutral, "
                f"{contradiction_count} contradicted"
            )
        else:
            reasons.append(
                f"Weak support: {entailment_count}/{total} claims entailed, "
                f"{contradiction_count} contradicted"
            )

        if contradiction_count:
            reasons.append(f"{contradiction_count} claim(s) contradicted by evidence")

        for cr in claim_results:
            if cr.label == "CONTRADICTION":
                reasons.append(f"Contradicted claim: \"{cr.claim[:80]}\"")
            elif cr.label == "NEUTRAL" and cr.score < 0.3:
                reasons.append(f"Unsupported claim: \"{cr.claim[:80]}\"")

        return reasons


def create_entailment_signal(**kwargs) -> EntailmentSignal:
    return EntailmentSignal(**kwargs)
