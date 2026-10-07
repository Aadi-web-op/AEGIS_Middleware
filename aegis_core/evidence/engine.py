"""AEGIS Evidence Intelligence Engine.

Single clean entry point:

    engine.evaluate(query=..., answer=..., evidence=...)

Runs the four evidence signals (relevance, entailment, contradiction,
completeness) and returns a structured result consumable by the central
AEGIS uncertainty/policy engine. This module is deliberately independent
of any final ANSWER/CAVEAT/ESCALATE/ABSTAIN policy.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from aegis_core.signals import (
    SignalName,
    SignalResult,
    RelevanceSignal,
    EntailmentSignal,
    ContradictionSignal,
    CompletenessSignal,
)

logger = logging.getLogger(__name__)

# Signals always produced by the engine, in a stable order.
SIGNAL_ORDER = (
    SignalName.RELEVANCE,
    SignalName.ENTAILMENT,
    SignalName.CONTRADICTION,
    SignalName.COMPLETENESS,
)


@dataclass
class EvidenceResult:
    """Structured output of the Evidence Intelligence Engine."""

    decision_ready: bool
    signals: Dict[str, Dict[str, Any]]
    reasons: List[str]
    timing_ms: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def relevance(self) -> Optional[Dict[str, Any]]:
        return self.signals.get(SignalName.RELEVANCE.value)

    @property
    def entailment(self) -> Optional[Dict[str, Any]]:
        return self.signals.get(SignalName.ENTAILMENT.value)

    @property
    def contradiction(self) -> Optional[Dict[str, Any]]:
        return self.signals.get(SignalName.CONTRADICTION.value)

    @property
    def completeness(self) -> Optional[Dict[str, Any]]:
        return self.signals.get(SignalName.COMPLETENESS.value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_ready": self.decision_ready,
            "signals": self.signals,
            "reasons": self.reasons,
            "timing_ms": self.timing_ms,
            "metadata": self.metadata,
        }


class EvidenceEngine:
    """
    Orchestrates the evidence intelligence signals.

    The engine never maps signals to ANSWER/CAVEAT/ESCALATE/ABSTAIN;
    that is the policy engine's job. It only produces evidence signals
    plus human-readable reasons.
    """

    def __init__(
        self,
        relevance: Optional[RelevanceSignal] = None,
        entailment: Optional[EntailmentSignal] = None,
        contradiction: Optional[ContradictionSignal] = None,
        completeness: Optional[CompletenessSignal] = None,
    ):
        self.relevance_signal = relevance or RelevanceSignal()
        self.entailment_signal = entailment or EntailmentSignal()
        self.contradiction_signal = contradiction or ContradictionSignal()
        self.completeness_signal = completeness or CompletenessSignal()

    def evaluate(
        self,
        query: str,
        answer: str,
        evidence: List[str],
        evidence_metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> EvidenceResult:
        """
        Evaluate a (query, answer, evidence) triple.

        Args:
            query: The user's original query.
            answer: The AI system's generated answer.
            evidence: Retrieved evidence passages.
            evidence_metadata: Optional per-evidence metadata
                (source, version, date) used by the contradiction signal.

        Returns:
            EvidenceResult with all four signals, reasons, and timing.
        """
        timing: Dict[str, float] = {}
        signals: Dict[str, Dict[str, Any]] = {}
        reasons: List[str] = []

        # Normalise inputs up-front so every signal sees the same shape.
        query = (query or "").strip()
        answer = (answer or "").strip()
        evidence = self._normalise_evidence(evidence)

        # 1. Relevance
        start = time.perf_counter()
        rel: SignalResult = self.relevance_signal.evaluate(query, answer, evidence)
        timing[SignalName.RELEVANCE.value] = (time.perf_counter() - start) * 1000
        signals[SignalName.RELEVANCE.value] = self._signal_dict(rel)

        # 2. Entailment
        start = time.perf_counter()
        ent: SignalResult = self.entailment_signal.evaluate(query, answer, evidence)
        timing[SignalName.ENTAILMENT.value] = (time.perf_counter() - start) * 1000
        signals[SignalName.ENTAILMENT.value] = self._signal_dict(ent)

        # 3. Contradiction
        start = time.perf_counter()
        con: SignalResult = self.contradiction_signal.evaluate(
            query, answer, evidence, evidence_metadata=evidence_metadata
        )
        timing[SignalName.CONTRADICTION.value] = (time.perf_counter() - start) * 1000
        signals[SignalName.CONTRADICTION.value] = self._signal_dict(con)

        # 4. Completeness
        start = time.perf_counter()
        com: SignalResult = self.completeness_signal.evaluate(query, answer, evidence)
        timing[SignalName.COMPLETENESS.value] = (time.perf_counter() - start) * 1000
        signals[SignalName.COMPLETENESS.value] = self._signal_dict(com)

        # Aggregate reasons in signal order.
        for name in SIGNAL_ORDER:
            reasons.extend(signals[name.value]["reasons"])

        result = EvidenceResult(
            decision_ready=True,
            signals=signals,
            reasons=reasons,
            timing_ms={k: round(v, 2) for k, v in timing.items()},
            metadata={
                "evidence_count": len(evidence),
                "query_length": len(query),
                "answer_length": len(answer),
                "total_latency_ms": round(sum(timing.values()), 2),
            },
        )
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_evidence(evidence: Optional[List[str]]) -> List[str]:
        """
        Normalise the evidence list: drop None, strip whitespace, drop
        empties, and de-duplicate while preserving order.
        """
        if not evidence:
            return []

        seen = set()
        out: List[str] = []
        for ev in evidence:
            if not isinstance(ev, str):
                logger.warning("Dropping non-string evidence: %r", ev)
                continue
            ev = ev.strip()
            if not ev:
                continue
            # De-duplicate exact repeats (case-insensitive) but keep first.
            key = ev.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)
        return out

    @staticmethod
    def _signal_dict(result: SignalResult) -> Dict[str, Any]:
        """Convert a SignalResult into a JSON-friendly dict."""
        return {
            "value": result.value,
            "reasons": result.reasons,
            "details": result.details,
        }


def create_evidence_engine(**kwargs) -> EvidenceEngine:
    """Factory for the EvidenceEngine."""
    return EvidenceEngine(**kwargs)
