from app.evidence.base import Signal
from app.schemas import EvidenceItem, SignalResult


class FixedSignal(Signal):
    """A fake signal that always returns the value it was given."""

    def __init__(self, name: str, value: float | None):
        self.name = name
        self._value = value

    def score(
        self, query: str, answer: str, evidence: list[EvidenceItem]
    ) -> SignalResult:
        return SignalResult(value=self._value, details={"stub": True})
        