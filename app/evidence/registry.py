from app.evidence.ambiguity import AmbiguitySignal
from app.evidence.base import Signal
from app.evidence.evidence_intelligence import evidence_intelligence_signals
from app.evidence.freshness import FreshnessSignal


def default_signals() -> list[Signal]:
    """The signals the live API uses.

    All six uncertainty signals are fully implemented and active:
      relevance, entailment, contradiction, completeness -> Evidence
                                                            Intelligence Engine
      freshness                                         -> FreshnessSignal
      ambiguity                                         -> AmbiguitySignal

    This function is the single source of truth for the live wiring, so it
    must never return a stub. Tests that want to hold a signal constant
    construct their own `FixedSignal` and inject it into `Evaluator`
    directly rather than filtering it out of this list.
    """
    return [
        *evidence_intelligence_signals(),
        FreshnessSignal(),
        AmbiguitySignal(),
    ]
