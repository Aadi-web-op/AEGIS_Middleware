from app.evidence.base import Signal
from app.evidence.evidence_intelligence import evidence_intelligence_signals
from app.evidence.stubs import FixedSignal


def default_signals() -> list[Signal]:
    """The signals the live API uses.

    Replace each stub with the real signal as teammates finish theirs:
      relevance, entailment, contradiction, completeness -> Sumit (done)
      freshness                                         -> Nandini
      ambiguity                                         -> Shatakshi

    FreshnessSignal and AmbiguitySignal are both implemented and tested on main;
    they are still stubbed here only because flipping them belongs to their
    owners. Until then those two values are fabricated, so any end-to-end
    number that depends on freshness or ambiguity is not yet meaningful.
    """
    return [
        *evidence_intelligence_signals(),
        FixedSignal("freshness", 0.90),  # TODO: Nandini -- app.evidence.freshness
        FixedSignal("ambiguity", 0.05),  # TODO: Shatakshi -- app.evidence.ambiguity
    ]
