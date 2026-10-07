"""Contradiction Signal - Detects conflicts between answer/evidence and between evidence sources."""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import itertools

from aegis_core.signals.base import BaseSignal, SignalResult, SignalName
from aegis_core.models.nli import NLIRunner
from aegis_core.utils.numeric_date import find_numeric_conflicts, find_date_conflicts

logger = logging.getLogger(__name__)


@dataclass
class ConflictPair:
    """A detected conflict between two text spans."""
    text_a: str
    text_b: str
    source_a: Optional[str] = None
    source_b: Optional[str] = None
    conflict_type: str = "nli"  # nli | numeric | date | version
    severity: str = "medium"  # low | medium | high
    score: float = 0.5
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text_a": self.text_a[:300],
            "text_b": self.text_b[:300],
            "source_a": self.source_a,
            "source_b": self.source_b,
            "conflict_type": self.conflict_type,
            "severity": self.severity,
            "score": self.score,
            "details": self.details,
        }


class ContradictionSignal(BaseSignal):
    """
    Contradiction signal with two independent checks:

    A. Answer vs evidence
       Does the answer conflict with any retrieved evidence?

    B. Evidence vs evidence
       Do the retrieved sources conflict with one another?

    Alongside NLI, this uses explicit numeric and date comparison, which is more
    reliable than NLI for the common policy-document case of "18 days" vs "12 days".

    Note on NLI direction: an NLI model cannot express "X contradicts Y" directly.
    We test both directions and treat high contradiction probability in either
    direction as a conflict.
    """

    def __init__(
        self,
        nli_model_id: str = "cross-encoder/nli-MiniLM2-L6-H768",
        nli_threshold: float = 0.7,
        max_pairs: int = 40,
        max_evidence: int = 8,
        numeric_conflict_weight: float = 1.0,
        date_conflict_weight: float = 1.0,
    ):
        self.nli = NLIRunner(nli_model_id)
        self.nli_threshold = nli_threshold
        self.max_pairs = max_pairs
        self.max_evidence = max_evidence
        self.numeric_conflict_weight = numeric_conflict_weight
        self.date_conflict_weight = date_conflict_weight

    @property
    def signal_name(self) -> SignalName:
        return SignalName.CONTRADICTION

    def evaluate(
        self,
        query: str,
        answer: str,
        evidence: List[str],
        **kwargs
    ) -> SignalResult:
        """
        Evaluate contradiction across answer/evidence and evidence/evidence.

        Args:
            query: User's query
            answer: AI system's answer
            evidence: Retrieved evidence passages
            **kwargs: May include 'evidence_metadata' (list of dicts with
                      'source'/'version'/'date') for version-aware checks.

        Returns:
            SignalResult with contradiction score, conflicting pairs, reasons.
        """
        if not evidence:
            return SignalResult(
                signal=SignalName.CONTRADICTION,
                value=0.0,
                reasons=["No evidence provided; no contradiction detectable"],
                details={
                    "evidence_count": 0,
                    "conflicting_pairs": [],
                    "numeric_mismatches": [],
                    "date_mismatches": [],
                    "checkable": False,
                },
            )

        evidence = evidence[: self.max_evidence]
        evidence_metadata = kwargs.get("evidence_metadata") or []

        answer_conflicts, answer_numeric, answer_dates = self._check_answer_vs_evidence(
            answer, evidence
        )
        ev_conflicts, ev_numeric, ev_dates = self._check_evidence_vs_evidence(evidence)
        version_conflicts = self._check_version_metadata(evidence, evidence_metadata)

        all_conflicts = answer_conflicts + ev_conflicts + version_conflicts
        numeric_mismatches = answer_numeric + ev_numeric
        date_mismatches = answer_dates + ev_dates

        score = self._score_contradiction(
            all_conflicts, numeric_mismatches, date_mismatches, len(evidence)
        )
        reasons = self._generate_reasons(
            score, all_conflicts, numeric_mismatches, date_mismatches, evidence
        )

        return SignalResult(
            signal=SignalName.CONTRADICTION,
            value=score,
            reasons=reasons,
            details={
                "contradiction_score": score,
                "answer_vs_evidence_conflicts": [c.to_dict() for c in answer_conflicts],
                "evidence_vs_evidence_conflicts": [c.to_dict() for c in ev_conflicts],
                "version_conflicts": [c.to_dict() for c in version_conflicts],
                "conflicting_pairs": [c.to_dict() for c in all_conflicts],
                "numeric_mismatches": numeric_mismatches,
                "date_mismatches": date_mismatches,
                "evidence_count": len(evidence),
                "nli_model": self.nli.model_id,
                "checkable": bool(answer.strip()) and bool(evidence),
            },
        )

    # ------------------------------------------------------------------
    # A. answer vs evidence
    # ------------------------------------------------------------------
    def _check_answer_vs_evidence(
        self, answer: str, evidence: List[str]
    ) -> Tuple[List[ConflictPair], List[Dict], List[Dict]]:
        conflicts: List[ConflictPair] = []
        numeric: List[Dict] = []
        dates: List[Dict] = []

        if not answer.strip():
            return conflicts, numeric, dates

        pairs = [(ev, answer) for ev in evidence]
        try:
            preds = self.nli.infer_batch(pairs)
        except Exception as exc:
            logger.warning("NLI unavailable for contradiction check: %s", exc)
            preds = []

        for ev, pred in zip(evidence, preds):
            # Contradiction in either direction counts. An NLI model trained on
            # (premise, hypothesis) asymmetry can miss a conflict if we only test
            # one ordering.
            if pred.contradiction >= self.nli_threshold:
                conflicts.append(
                    ConflictPair(
                        text_a=answer,
                        text_b=ev,
                        conflict_type="nli",
                        severity="high" if pred.contradiction >= 0.9 else "medium",
                        score=pred.contradiction,
                        details=pred.to_dict(),
                    )
                )

            for conflict in find_numeric_conflicts(answer, ev):
                numeric.append({"scope": "answer_vs_evidence", **conflict})
            for conflict in find_date_conflicts(answer, ev):
                dates.append({"scope": "answer_vs_evidence", **conflict})

        return conflicts, numeric, dates

    # ------------------------------------------------------------------
    # B. evidence vs evidence
    # ------------------------------------------------------------------
    def _check_evidence_vs_evidence(
        self, evidence: List[str]
    ) -> Tuple[List[ConflictPair], List[Dict], List[Dict]]:
        conflicts: List[ConflictPair] = []
        numeric: List[Dict] = []
        dates: List[Dict] = []

        index_pairs = list(itertools.combinations(range(len(evidence)), 2))
        if len(index_pairs) > self.max_pairs:
            index_pairs = index_pairs[: self.max_pairs]

        nli_pairs = [(evidence[i], evidence[j]) for i, j in index_pairs]
        try:
            preds = self.nli.infer_batch(nli_pairs)
        except Exception as exc:
            logger.warning("NLI unavailable for evidence conflict check: %s", exc)
            preds = []

        for (i, j), pred in zip(index_pairs, preds):
            a, b = evidence[i], evidence[j]
            if pred.contradiction >= self.nli_threshold:
                conflicts.append(
                    ConflictPair(
                        text_a=a,
                        text_b=b,
                        source_a=f"evidence[{i}]",
                        source_b=f"evidence[{j}]",
                        conflict_type="nli",
                        severity="high" if pred.contradiction >= 0.9 else "medium",
                        score=pred.contradiction,
                        details=pred.to_dict(),
                    )
                )

            for conflict in find_numeric_conflicts(a, b):
                numeric.append(
                    {
                        "scope": "evidence_vs_evidence",
                        "source_a": f"evidence[{i}]",
                        "source_b": f"evidence[{j}]",
                        **conflict,
                    }
                )
            for conflict in find_date_conflicts(a, b):
                dates.append(
                    {
                        "scope": "evidence_vs_evidence",
                        "source_a": f"evidence[{i}]",
                        "source_b": f"evidence[{j}]",
                        **conflict,
                    }
                )

        return conflicts, numeric, dates

    # ------------------------------------------------------------------
    # C. version metadata
    # ------------------------------------------------------------------
    def _check_version_metadata(
        self, evidence: List[str], metadata: List[Dict[str, Any]]
    ) -> List[ConflictPair]:
        """
        Detect same-topic-different-version sources.

        Only reports a version conflict when two sources describe the same topic
        (high lexical overlap) but carry different version labels. Different
        wording alone is never treated as a version conflict.
        """
        conflicts: List[ConflictPair] = []
        if not metadata or len(metadata) < 2:
            return conflicts

        for i, j in itertools.combinations(range(len(evidence)), 2):
            if j >= len(metadata) or i >= len(metadata):
                continue
            meta_a, meta_b = metadata[i], metadata[j]
            ver_a = str(meta_a.get("version") or "").strip()
            ver_b = str(meta_b.get("version") or "").strip()
            if not ver_a or not ver_b or ver_a == ver_b:
                continue

            overlap = self._token_overlap(evidence[i], evidence[j])
            if overlap >= 0.6:
                conflicts.append(
                    ConflictPair(
                        text_a=evidence[i],
                        text_b=evidence[j],
                        source_a=str(meta_a.get("source") or f"evidence[{i}]"),
                        source_b=str(meta_b.get("source") or f"evidence[{j}]"),
                        conflict_type="version",
                        severity="medium",
                        score=overlap,
                        details={
                            "version_a": ver_a,
                            "version_b": ver_b,
                            "topic_overlap": round(overlap, 3),
                        },
                    )
                )
        return conflicts

    @staticmethod
    def _token_overlap(a: str, b: str) -> float:
        """Jaccard token overlap - cheap topic-similarity proxy."""
        ta = {t for t in a.lower().split() if len(t) > 3}
        tb = {t for t in b.lower().split() if len(t) > 3}
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    # ------------------------------------------------------------------
    # scoring
    # ------------------------------------------------------------------
    def _score_contradiction(
        self,
        conflicts: List[ConflictPair],
        numeric: List[Dict],
        dates: List[Dict],
        evidence_count: int,
    ) -> float:
        """
        Aggregate into a contradiction score in [0, 1].

        Higher = more contradiction. Numeric and date mismatches are treated as
        high-confidence signals because they are exact, rule-based comparisons.
        """
        if not conflicts and not numeric and not dates:
            return 0.0

        max_nli = max((c.score for c in conflicts), default=0.0)
        score = max_nli

        if numeric:
            score = max(
                score,
                min(1.0, 0.85 * self.numeric_conflict_weight * min(len(numeric), 2) / 2 + 0.4),
            )
        if dates:
            score = max(
                score,
                min(1.0, 0.85 * self.date_conflict_weight * min(len(dates), 2) / 2 + 0.4),
            )

        # Multiple independent conflicts reinforce each other.
        extra = len(conflicts) - 1
        if extra > 0:
            score = min(1.0, score + 0.05 * extra)

        return round(max(0.0, min(1.0, score)), 4)

    def _generate_reasons(
        self,
        score: float,
        conflicts: List[ConflictPair],
        numeric: List[Dict],
        dates: List[Dict],
        evidence: List[str],
    ) -> List[str]:
        reasons: List[str] = []

        if numeric:
            first = numeric[0]
            reasons.append(
                f"Numeric mismatch detected: {first.get('text_a')} vs {first.get('text_b')} "
                f"({first.get('scope')})"
            )
        if dates:
            first = dates[0]
            reasons.append(f"Date mismatch detected between sources ({first.get('scope')})")

        nli_conflicts = [c for c in conflicts if c.conflict_type == "nli"]
        if nli_conflicts:
            aev = [c for c in nli_conflicts if c.source_a is None]
            eve = [c for c in nli_conflicts if c.source_a is not None]
            if aev:
                reasons.append(f"Answer conflicts with {len(aev)} evidence passage(s)")
            if eve:
                reasons.append(f"{len(eve)} conflicting source pair(s) detected")

        version_conflicts = [c for c in conflicts if c.conflict_type == "version"]
        if version_conflicts:
            vc = version_conflicts[0]
            reasons.append(
                f"Version mismatch: {vc.details.get('version_a')} vs {vc.details.get('version_b')} "
                "on the same topic"
            )

        if not reasons:
            reasons.append("No contradiction detected between answer and evidence")

        if score >= 0.8:
            reasons.append("High contradiction risk; evidence is inconsistent")
        elif score >= 0.5:
            reasons.append("Moderate contradiction risk; some evidence conflicts")

        return reasons


def create_contradiction_signal(**kwargs) -> ContradictionSignal:
    return ContradictionSignal(**kwargs)
