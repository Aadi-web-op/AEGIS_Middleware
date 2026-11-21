"""AEGIS Evidence Intelligence signals."""

from aegis_core.signals.base import BaseSignal, SignalResult, SignalName
from aegis_core.signals.relevance import RelevanceSignal, create_relevance_signal
from aegis_core.signals.entailment import EntailmentSignal, create_entailment_signal
from aegis_core.signals.contradiction import ContradictionSignal, create_contradiction_signal
from aegis_core.signals.completeness import CompletenessSignal, create_completeness_signal

__all__ = [
    "BaseSignal",
    "SignalResult",
    "SignalName",
    "RelevanceSignal",
    "EntailmentSignal",
    "ContradictionSignal",
    "CompletenessSignal",
    "create_relevance_signal",
    "create_entailment_signal",
    "create_contradiction_signal",
    "create_completeness_signal",
]
