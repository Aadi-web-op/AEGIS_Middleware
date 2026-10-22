"""Contradiction Signal - Detects conflicts between answer/evidence and between evidence sources."""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import itertools

from aegis_core.signals.base import BaseSignal, SignalResult, SignalName
from aegis_core.models.nli import NLIRunner
from aegis_core.utils.numeric_date import find_numeric_conflicts, find_date_conflicts

logger = logging.getLogger(__name__)

# Conflict text carried in `details` is a preview, never a full passage.
_PREVIEW_CHARS = 120


def _fmt_value(value: Any) -> Optional[str]:
    """Render a detected numeric value as a short string ("18", not "18.0")."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# Internal conflict_type -> the conflict kind vocabulary used by the
# decision graph. "nli" is a disagreement between statements with no
# scalar value to compare, hence "statement".
_KIND = {
    "nli": "statement",
    "numeric": "numeric",
    "date": "date",
    "version": "version",
}

# Scopes whose conflicts are between two evidence passages, and so can
# become an evidence-to-evidence edge in the graph. An answer-vs-evidence
# conflict has only one evidence index and is reported as a diagnostic.
_PAIRED_SCOPES = ("evidence_vs_evidence", "version")


@dataclass
class ConflictPair:
    """A detected conflict between two text spans.

    `index_a` / `index_b` are positions in the evidence list this signal
    was given, or None where the span is not an evidence passage (the
    answer has no evidence index). `scope` says what the two sides are,
    so a consumer can tell an evidence-to-evidence conflict from an
    answer-to-evidence one without inspecting `source_a`.
    """
    text_a: str
    text_b: str
    source_a: Optional[str] = None
    source_b: Optional[str] = None
    conflict_type: str = "nli"  # nli | numeric | date | version
    severity: str = "medium"  # low | medium | high
    score: float = 0.5
    details: Dict[str, Any] = field(default_factory=dict)
    index_a: Optional[int] = None
    index_b: Optional[int] = None
    scope: str = ""

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
            "index_a": self.index_a,
            "index_b": self.index_b,
            "scope": self.scope,
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
                    "conflicts": [],
                    "checkable": False,
                },
            )

        # Indices reported in `details` refer to this list. Truncation keeps
        # the prefix, so index i here is index i of the list the signal was
        # given; `evidence_truncated` says higher indices were never compared.
        supplied_count = len(evidence)
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

        # Built from the findings above, after scoring, and never passed back
        # into it. The score's interpretation is unchanged: higher still means
        # more contradiction, and it is not inverted here or anywhere else.
        graph_conflicts = self._graph_conflicts(
            all_conflicts, numeric_mismatches, date_mismatches, evidence_metadata
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
                # --- graph-facing conflict detail ---
                "conflicts": graph_conflicts,
                "evidence_considered": len(evidence),
                "evidence_supplied": supplied_count,
                "evidence_truncated": supplied_count > len(evidence),
                "evidence_index_base": 0,
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

        for ei, (ev, pred) in enumerate(zip(evidence, preds)):
            # Contradiction in either direction counts. An NLI model trained on
            # (premise, hypothesis) asymmetry can miss a conflict if we only test
            # one ordering.
            if pred.contradiction >= self.nli_threshold:
                conflicts.append(
                    ConflictPair(
                        text_a=answer,
                        text_b=ev,
                        source_b=f"evidence[{ei}]",
                        conflict_type="nli",
                        severity="high" if pred.contradiction >= 0.9 else "medium",
                        score=pred.contradiction,
                        details=pred.to_dict(),
                        index_a=None,  # the answer is not an evidence passage
                        index_b=ei,
                        scope="answer_vs_evidence",
                    )
                )

            for conflict in find_numeric_conflicts(answer, ev):
                numeric.append(
                    {
                        "scope": "answer_vs_evidence",
                        "index_a": None,
                        "index_b": ei,
                        "source_b": f"evidence[{ei}]",
                        **conflict,
                    }
                )
            for conflict in find_date_conflicts(answer, ev):
                dates.append(
                    {
                        "scope": "answer_vs_evidence",
                        "index_a": None,
                        "index_b": ei,
                        "source_b": f"evidence[{ei}]",
                        **conflict,
                    }
                )

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
                        index_a=i,
                        index_b=j,
                        scope="evidence_vs_evidence",
                    )
                )

            for conflict in find_numeric_conflicts(a, b):
                numeric.append(
                    {
                        "scope": "evidence_vs_evidence",
                        "index_a": i,
                        "index_b": j,
                        "source_a": f"evidence[{i}]",
                        "source_b": f"evidence[{j}]",
                        **conflict,
                    }
                )
            for conflict in find_date_conflicts(a, b):
                dates.append(
                    {
                        "scope": "evidence_vs_evidence",
                        "index_a": i,
                        "index_b": j,
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
                        index_a=i,
                        index_b=j,
                        scope="version",
                    )
                )
        return conflicts

    # ------------------------------------------------------------------
    # D. graph-facing projection
    # ------------------------------------------------------------------
    def _graph_conflicts(
        self,
        nli_and_version: List[ConflictPair],
        numeric: List[Dict[str, Any]],
        dates: List[Dict[str, Any]],
        metadata: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Flatten every detected conflict into one graph-ready list.

        This is a *projection* of findings that were already made and
        scored. It detects nothing of its own and is never fed back into
        `_score_contradiction`, so adding it cannot move the contradiction
        score.

        `graph_edge_eligible` is the honesty flag the graph writer keys on:
        it is True only for a conflict between two evidence passages whose
        indices are both known. An answer-vs-evidence conflict, or a
        conflict whose source pair could not be established, is still
        reported here as a diagnostic but is marked ineligible, so the
        graph omits the edge instead of inventing one.
        """
        out: List[Dict[str, Any]] = []
        seen = set()

        def emit(entry: Dict[str, Any]) -> None:
            indices = [i for i in (entry["index_a"], entry["index_b"]) if i is not None]
            entry["evidence_indices"] = indices
            entry["graph_edge_eligible"] = (
                entry["scope"] in _PAIRED_SCOPES
                and entry["index_a"] is not None
                and entry["index_b"] is not None
            )
            key = (
                entry["kind"], entry["scope"], tuple(indices),
                entry["value_a"], entry["value_b"],
            )
            if key in seen:
                return
            seen.add(key)
            out.append(entry)

        for pair in nli_and_version:
            kind = _KIND.get(pair.conflict_type, pair.conflict_type)
            if kind == "version":
                reason = (
                    f"Version mismatch: {pair.details.get('version_a')} vs "
                    f"{pair.details.get('version_b')} on the same topic."
                )
                value_a = pair.details.get("version_a")
                value_b = pair.details.get("version_b")
            else:
                reason = (
                    "Natural-language inference reports the two statements "
                    f"contradict (p={pair.score:.2f})."
                )
                # A statement-level disagreement has no scalar value to report.
                value_a = value_b = None
            emit(
                self._conflict_entry(
                    kind=kind,
                    scope=pair.scope,
                    index_a=pair.index_a,
                    index_b=pair.index_b,
                    value_a=value_a,
                    value_b=value_b,
                    text_a=pair.text_a,
                    text_b=pair.text_b,
                    reason=reason,
                    severity=pair.severity,
                    score=pair.score,
                    metadata=metadata,
                    fallback_source_a=pair.source_a,
                    fallback_source_b=pair.source_b,
                )
            )

        for conflict in numeric:
            emit(
                self._conflict_entry(
                    kind="numeric",
                    scope=str(conflict.get("scope") or ""),
                    index_a=conflict.get("index_a"),
                    index_b=conflict.get("index_b"),
                    value_a=_fmt_value(conflict.get("value_a")),
                    value_b=_fmt_value(conflict.get("value_b")),
                    text_a=str(conflict.get("text_a") or ""),
                    text_b=str(conflict.get("text_b") or ""),
                    reason=(
                        f"Numeric mismatch: {conflict.get('text_a')} vs "
                        f"{conflict.get('text_b')}."
                    ),
                    severity="high",
                    score=1.0,
                    metadata=metadata,
                    fallback_source_a=conflict.get("source_a"),
                    fallback_source_b=conflict.get("source_b"),
                    extra={
                        "family": conflict.get("family"),
                        "unit_a": conflict.get("unit_a"),
                        "unit_b": conflict.get("unit_b"),
                        "qualifier_a": conflict.get("qualifier_a"),
                        "qualifier_b": conflict.get("qualifier_b"),
                    },
                )
            )

        for conflict in dates:
            date_a = conflict.get("date_a") or {}
            date_b = conflict.get("date_b") or {}
            value_a = date_a.get("iso") or date_a.get("text")
            value_b = date_b.get("iso") or date_b.get("text")
            emit(
                self._conflict_entry(
                    kind="date",
                    scope=str(conflict.get("scope") or ""),
                    index_a=conflict.get("index_a"),
                    index_b=conflict.get("index_b"),
                    value_a=value_a,
                    value_b=value_b,
                    text_a=str(date_a.get("text") or ""),
                    text_b=str(date_b.get("text") or ""),
                    reason=f"Date mismatch: {value_a} vs {value_b}.",
                    severity="high",
                    score=1.0,
                    metadata=metadata,
                    fallback_source_a=conflict.get("source_a"),
                    fallback_source_b=conflict.get("source_b"),
                )
            )

        return out

    @staticmethod
    def _conflict_entry(
        *,
        kind: str,
        scope: str,
        index_a: Optional[int],
        index_b: Optional[int],
        value_a: Any,
        value_b: Any,
        text_a: str,
        text_b: str,
        reason: str,
        severity: str,
        score: float,
        metadata: List[Dict[str, Any]],
        fallback_source_a: Optional[str] = None,
        fallback_source_b: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build one conflict record, resolving source/version from metadata."""
        meta_a = metadata[index_a] if index_a is not None and index_a < len(metadata) else {}
        meta_b = metadata[index_b] if index_b is not None and index_b < len(metadata) else {}
        entry: Dict[str, Any] = {
            "kind": kind,
            "scope": scope,
            "index_a": index_a,
            "index_b": index_b,
            "value_a": value_a,
            "value_b": value_b,
            # Previews only. The graph writer re-enforces its own cap; this
            # keeps full passage text out of the details payload entirely.
            "text_a": text_a[:_PREVIEW_CHARS],
            "text_b": text_b[:_PREVIEW_CHARS],
            "source_a": (meta_a.get("source") if meta_a else None) or fallback_source_a,
            "source_b": (meta_b.get("source") if meta_b else None) or fallback_source_b,
            "version_a": meta_a.get("version") if meta_a else None,
            "version_b": meta_b.get("version") if meta_b else None,
            "date_a": meta_a.get("date") if meta_a else None,
            "date_b": meta_b.get("date") if meta_b else None,
            "reason": reason,
            "severity": severity,
            "score": round(float(score), 4),
        }
        if extra:
            entry.update({k: v for k, v in extra.items() if v is not None})
        return entry

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
