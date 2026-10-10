"""Adapter between the Evidence Intelligence Engine and the central evaluator.

`aegis_core` and `app` describe a signal differently, and the two shapes are not
interchangeable:

    aegis_core  @dataclass SignalResult(signal: SignalName, value: float,
                                        reasons: list[str], details: dict)
                one engine call produces all four signals at once

    app         pydantic  SignalResult(value: float | None,
                                        reasons: list[Reason], details: dict)
                one Signal object per signal, each called separately

This module bridges the two without either side learning about the other.
`aegis_core` stays free of policy and of pydantic; `app.evidence.base.Signal`,
`app.schemas` and the central evaluator are untouched.

Ownership: the engine measures evidence. Deciding what a measurement means
belongs to the policy engine, so nothing here compares a value to a threshold.
A `Reason` is attached only where the engine itself already reported a concrete
finding -- an unsupported claim, a numeric conflict, an uncovered aspect of the
query, a passage below the engine's own relevance threshold.

`contradiction` is passed through raw and uninverted: a high value still means
"conflict present". `scoring.py` converts it with `agreement = 1 - contradiction`
and `policy.py` reads it as a veto. Inverting it here would double-invert it.
"""

from __future__ import annotations

import datetime
import threading
from typing import Any, Dict, List, Optional, Tuple

from aegis_core.evidence.engine import EvidenceEngine, EvidenceResult
from app.evidence.base import Signal
from app.schemas import EvidenceItem, Reason, ReasonCode, SignalResult

# Which reason code each signal raises when the engine reports a finding.
# Mirrors the mapping the policy engine uses for the same signal names.
_REASON_CODE = {
    "relevance": ReasonCode.LOW_RELEVANCE,
    "entailment": ReasonCode.UNSUPPORTED_CLAIM,
    "contradiction": ReasonCode.CONTRADICTION,
    "completeness": ReasonCode.INCOMPLETE_EVIDENCE,
}

# Labels the NLI runner uses for a claim the evidence does not support.
_UNSUPPORTED_LABELS = {"CONTRADICTION", "NEUTRAL"}

# details keys holding conflicts found by the contradiction signal, each with
# the singular and plural wording used to report it.
_CONFLICT_KEYS = (
    ("numeric_mismatches", "numeric mismatch", "numeric mismatches"),
    ("date_mismatches", "date mismatch", "date mismatches"),
    (
        "answer_vs_evidence_conflicts",
        "conflict between the answer and the evidence",
        "conflicts between the answer and the evidence",
    ),
    (
        "evidence_vs_evidence_conflicts",
        "conflict between two evidence sources",
        "conflicts between evidence sources",
    ),
    ("version_conflicts", "version conflict", "version conflicts"),
)

_EvidenceKey = Tuple[Tuple[str, str, str, str], ...]
_CacheKey = Tuple[str, str, _EvidenceKey]


def _evidence_payload(
    evidence: List[EvidenceItem],
) -> Tuple[List[str], Optional[List[Dict[str, Any]]]]:
    """Split `EvidenceItem`s into the texts and metadata the engine expects.

    The engine takes passages as plain strings plus a parallel list of
    source/version/date dicts. Dates arrive as `datetime.date` and go out as
    ISO strings, which is what the contradiction signal's date checks parse.
    Metadata is omitted entirely when no item carries a source or version, so
    the engine can skip its version-conflict pass.
    """
    texts: List[str] = []
    metadata: List[Dict[str, Any]] = []

    for item in evidence:
        texts.append(item.text)
        metadata.append(
            {
                "source": item.source,
                "version": item.version,
                "date": item.date.isoformat() if item.date else None,
            }
        )

    useful = any(m["source"] or m["version"] or m["date"] for m in metadata)
    return texts, (metadata if useful else None)


def _cache_key(query: str, answer: str, evidence: List[EvidenceItem]) -> _CacheKey:
    return (
        query,
        answer,
        tuple(
            (
                item.text,
                item.source or "",
                item.version or "",
                item.date.isoformat() if item.date else "",
            )
            for item in evidence
        ),
    )


class EvidenceIntelligence:
    """Runs the Evidence Intelligence Engine once per request.

    The engine computes all four signals in a single pass, but the evaluator
    calls each `Signal` separately. Without sharing, one request would load and
    run the models four times -- measured at roughly 4x 32-70 ms on a warm CPU.
    This holds the result of the most recent (query, answer, evidence) triple so
    the four signals of one request cost one engine call.

    Only the latest triple is kept: the evaluator runs its signals back to back,
    so a single slot is all that is needed, and nothing accumulates between
    requests. A raised exception is never cached -- it propagates to every
    signal's `run()` wrapper, which turns it into `value=None` plus a
    SIGNAL_UNAVAILABLE reason, and the policy engine then applies its floor for
    an uncomputable signal.
    """

    def __init__(self, engine: Optional[EvidenceEngine] = None):
        self.engine = engine or EvidenceEngine()
        self._lock = threading.Lock()
        self._key: Optional[_CacheKey] = None
        self._result: Optional[EvidenceResult] = None

    def result_for(
        self, query: str, answer: str, evidence: List[EvidenceItem]
    ) -> EvidenceResult:
        key = _cache_key(query, answer, evidence)

        with self._lock:
            if self._key == key and self._result is not None:
                return self._result

            texts, metadata = _evidence_payload(evidence)
            result = self.engine.evaluate(
                query=query,
                answer=answer,
                evidence=texts,
                evidence_metadata=metadata,
            )

            # Only reached when evaluate() returned; a raise leaves the previous
            # entry in place and reaches the caller's run() wrapper untouched.
            self._key = key
            self._result = result
            return result


class _EvidenceSignal(Signal):
    """One app-facing signal backed by the shared engine result."""

    def __init__(self, intelligence: EvidenceIntelligence):
        self.intelligence = intelligence

    def _findings(self, details: Dict[str, Any]) -> List[str]:
        """Concrete problems the engine reported, as messages. Empty = none."""
        raise NotImplementedError

    def score(
        self, query: str, answer: str, evidence: list[EvidenceItem]
    ) -> SignalResult:
        result = self.intelligence.result_for(query, answer, evidence)
        body = result.signals[self.name]
        details = dict(body["details"])

        # Keep every engine reason, including the purely informational ones
        # ("No contradiction detected"), which must not become a Reason.
        details["engine_reasons"] = list(body["reasons"])
        details["engine_latency_ms"] = result.timing_ms.get(self.name)

        reasons = [
            Reason(code=_REASON_CODE[self.name], message=message)
            for message in self._findings(body["details"])
        ]
        return SignalResult(value=body["value"], reasons=reasons, details=details)


class RelevanceSignal(_EvidenceSignal):
    """Is the evidence related to the query? (embeddings, optional re-ranking)"""

    name = "relevance"

    def _findings(self, details: Dict[str, Any]) -> List[str]:
        relevant = details.get("relevant_count")
        total = details.get("total_evidence_count")
        if not isinstance(relevant, int) or not isinstance(total, int) or total == 0:
            return []
        if relevant >= total:
            return []
        off_topic = total - relevant
        subject = "passage is" if off_topic == 1 else "passages are"
        return [
            f"{off_topic} of {total} evidence {subject} not related to the "
            f"question (below the engine's relevance threshold of "
            f"{details.get('similarity_threshold')})."
        ]


class EntailmentSignal(_EvidenceSignal):
    """Does the evidence support each claim in the answer? (claim split + NLI)"""

    name = "entailment"

    def _findings(self, details: Dict[str, Any]) -> List[str]:
        claims = details.get("claims")
        if not isinstance(claims, list):
            return []

        unsupported = [
            claim
            for claim in claims
            if isinstance(claim, dict)
            and str(claim.get("label", "")).upper() in _UNSUPPORTED_LABELS
        ]
        if not unsupported:
            return []

        messages = [
            f"{len(unsupported)} of {len(claims)} claims in the answer are not "
            f"supported by the evidence."
        ]
        for claim in unsupported:
            verb = (
                "is contradicted by"
                if str(claim.get("label", "")).upper() == "CONTRADICTION"
                else "is not backed by"
            )
            messages.append(f'The claim "{claim.get("claim")}" {verb} the evidence.')
        return messages


class ContradictionSignal(_EvidenceSignal):
    """Do the answer and evidence, or two sources, conflict?

    Inverted by convention: a higher value is a warning, not a good outcome.
    Passed through unchanged for `scoring.py` and `policy.py` to interpret.
    """

    name = "contradiction"

    def _findings(self, details: Dict[str, Any]) -> List[str]:
        messages: List[str] = []
        for key, singular, plural in _CONFLICT_KEYS:
            conflicts = details.get(key)
            if not isinstance(conflicts, list) or not conflicts:
                continue
            count = len(conflicts)
            messages.append(
                f"The evidence shows {count} {singular if count == 1 else plural}."
            )
        return messages


class CompletenessSignal(_EvidenceSignal):
    """Does the evidence cover every part of the query? (decompose + coverage)"""

    name = "completeness"

    def _findings(self, details: Dict[str, Any]) -> List[str]:
        missing = details.get("missing_aspects")
        if not isinstance(missing, list) or not missing:
            return []
        aspects = ", ".join(f'"{aspect}"' for aspect in missing)
        total = details.get("total_aspects")
        return [
            f"The evidence does not cover {len(missing)} of {total} parts of the "
            f"question: {aspects}."
        ]


def evidence_intelligence_signals(
    engine: Optional[EvidenceEngine] = None,
) -> List[Signal]:
    """The four Evidence Intelligence signals, sharing one engine call."""
    intelligence = EvidenceIntelligence(engine)
    return [
        RelevanceSignal(intelligence),
        EntailmentSignal(intelligence),
        ContradictionSignal(intelligence),
        CompletenessSignal(intelligence),
    ]
