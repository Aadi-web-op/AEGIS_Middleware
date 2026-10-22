"""Entailment/Support Signal - Verifies whether evidence supports claims in the answer.

Pipeline:
  ANSWER -> claim extraction -> claim/evidence pairs -> batched NLI -> aggregate

All (premise=evidence, hypothesis=claim) pairs for the whole evaluation are
collected and run through one batched NLI forward pass, which is the
dominant performance win on CPU (see models/nli.py).
"""

import logging
import re
from dataclasses import dataclass, field
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


# NLI label -> the claim status vocabulary the central schema already uses
# (app.schemas.ClaimStatus). A claim the evidence neither entails nor
# contradicts is UNSUPPORTED, not CONTRADICTED.
_LABEL_TO_STATUS = {
    "ENTAILMENT": "SUPPORTED",
    "CONTRADICTION": "CONTRADICTED",
    "NEUTRAL": "UNSUPPORTED",
}


@dataclass
class ClaimResult:
    """Result of verifying a single claim against the evidence.

    `evidence` / `evidence_scores` / `label` / `score` are the original
    diagnostic fields and keep their meaning. The index fields are the
    graph-facing addition: they name *which* evidence passage decided the
    claim, using the index of the evidence list this signal was given.

    The index lists are derived purely from the model's own threshold
    crossings. They are empty when nothing crossed a threshold, and empty
    when the NLI model was unavailable (`nli_available` tells the two
    apart). Unlike `evidence`, they are never back-filled with a
    "nearest" passage, so a consumer can trust that an index listed here
    is a real model finding.
    """
    claim: str
    label: str  # "ENTAILMENT" | "CONTRADICTION" | "NEUTRAL"
    score: float
    evidence: List[str]
    evidence_scores: List[float]
    claim_index: int = 0
    supporting_evidence_indices: List[int] = field(default_factory=list)
    contradicting_evidence_indices: List[int] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    nli_available: bool = False

    @property
    def status(self) -> str:
        """Claim status in the central schema's vocabulary."""
        return _LABEL_TO_STATUS.get(self.label, "UNSUPPORTED")

    @property
    def evidence_indices(self) -> List[int]:
        """Every evidence index that decided this claim, in ascending order."""
        return sorted(
            set(self.supporting_evidence_indices)
            | set(self.contradicting_evidence_indices)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "label": self.label,
            "score": round(self.score, 4),
            "evidence": self.evidence,
            "evidence_scores": [round(s, 4) for s in self.evidence_scores],
            # --- claim-level detail for the decision graph ---
            "claim_index": self.claim_index,
            "status": self.status,
            "support": round(self.score, 4),
            "supporting_evidence_indices": list(self.supporting_evidence_indices),
            "contradicting_evidence_indices": list(self.contradicting_evidence_indices),
            "evidence_indices": self.evidence_indices,
            "reasons": list(self.reasons),
            "nli_available": self.nli_available,
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

        # Indices reported in `details` refer to this list. Truncation keeps
        # the prefix, so index i here is index i of the list handed to the
        # signal; `evidence_truncated` says that higher indices exist but
        # were never examined, so their absence is not a model finding.
        supplied_count = len(evidence)
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
                # --- index provenance for the decision graph ---
                "evidence_considered": len(evidence),
                "evidence_supplied": supplied_count,
                "evidence_truncated": supplied_count > len(evidence),
                "evidence_index_base": 0,
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
            results.append(self._resolve_claim(ci, claim, evidence, per_claim[ci]))
        return results

    def _resolve_claim(
        self,
        claim_index: int,
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

        # Evidence indices are read straight off the model's threshold
        # crossings, independently of `best_label`. A claim that one passage
        # entails and another contradicts therefore reports both, which is
        # what the graph needs in order to draw both edges.
        supporting_indices = [
            ei for ei, p in enumerate(preds)
            if p is not None and p.entailment >= self.entailment_threshold
        ]
        contradicting_indices = [
            ei for ei, p in enumerate(preds)
            if p is not None and p.contradiction >= self.contradiction_threshold
        ]
        nli_available = any(p is not None for p in preds)

        # The textual `evidence` field keeps its original fallback: when no
        # passage crossed a threshold it still shows the first passage, so
        # existing readers see what they always saw. The index lists above
        # deliberately stay empty in that case rather than naming a passage
        # the model never actually implicated.
        if not supporting:
            supporting = evidence[:1]

        return ClaimResult(
            claim=claim,
            label=best_label,
            score=round(max(0.0, min(1.0, score)), 4),
            evidence=supporting[:3],
            evidence_scores=ent_scores,
            claim_index=claim_index,
            supporting_evidence_indices=supporting_indices,
            contradicting_evidence_indices=contradicting_indices,
            reasons=self._claim_reasons(
                best_label, score, supporting_indices,
                contradicting_indices, nli_available,
            ),
            nli_available=nli_available,
        )

    def _claim_reasons(
        self,
        label: str,
        score: float,
        supporting: List[int],
        contradicting: List[int],
        nli_available: bool,
    ) -> List[str]:
        """Per-claim diagnostics, naming the evidence indices involved."""
        if not nli_available:
            return ["NLI model unavailable; this claim could not be verified."]

        reasons: List[str] = []
        if label == "ENTAILMENT" and supporting:
            reasons.append(f"Entailed by evidence {supporting}.")
        elif label == "CONTRADICTION" and contradicting:
            reasons.append(f"Contradicted by evidence {contradicting}.")
        elif label == "NEUTRAL":
            reasons.append(
                "No evidence passage entails or contradicts this claim "
                f"above threshold (best neutral-weighted support {score:.2f})."
            )

        # A claim can be entailed by one source and contradicted by another.
        if supporting and contradicting:
            reasons.append(
                f"Also contradicted by evidence {contradicting}; "
                "sources disagree about this claim."
            )
        return reasons

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
