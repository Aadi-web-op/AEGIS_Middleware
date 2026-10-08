from app.evidence.base import Signal
from app.evidence.stubs import FixedSignal


def default_signals() -> list[Signal]:
    """The signals the live API uses.

    Replace each stub with the real signal as teammates finish theirs:
      relevance, entailment, contradiction, completeness -> Sumit
      freshness                                         -> Nandini
      ambiguity                                         -> Shatakshi
    """
    return [
        FixedSignal("relevance", 0.90),      # TODO: Sumit
        FixedSignal("entailment", 0.90),     # TODO: Sumit
        FixedSignal("contradiction", 0.05),  # TODO: Sumit
        FixedSignal("freshness", 0.90),      # TODO: Nandini
        FixedSignal("completeness", 0.90),   # TODO: Sumit
        FixedSignal("ambiguity", 0.05),      # TODO: Shatakshi
    ]
    