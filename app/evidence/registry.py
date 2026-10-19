from app.evidence.ambiguity import AmbiguitySignal
from app.evidence.base import Signal
from app.evidence.evidence_intelligence import evidence_intelligence_signals
from app.evidence.stubs import FixedSignal


def default_signals() -> list[Signal]:
    """The signals the live API uses.

    Replace each stub with the real signal as teammates finish theirs:
      relevance, entailment, contradiction, completeness -> Sumit (done)
      freshness                                         -> Nandini
      ambiguity                                         -> Shatakshi (done)
    """
    return [
        *evidence_intelligence_signals(),
        FixedSignal("freshness", 0.90),  # TODO: Nandini -- app.evidence.freshness
        AmbiguitySignal(),
    ]
