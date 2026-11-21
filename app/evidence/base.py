import logging
import time
from abc import ABC, abstractmethod

from app.schemas import EvidenceItem, Reason, ReasonCode, SignalResult

logger = logging.getLogger(__name__)


class Signal(ABC):
    """Base class every uncertainty signal must follow.

    Subclasses set `name` and implement `score()`. The engine always calls
    `run()`, never `score()` directly, so a crashing signal can never crash
    the whole evaluation.

    Convention: contradiction and ambiguity are "bad" signals (higher = worse).
    The scoring engine converts them with 1 - value. Signals just report
    their raw measurement.
    """

    name: str

    @abstractmethod
    def score(
        self, query: str, answer: str, evidence: list[EvidenceItem]
    ) -> SignalResult:
        """Measure one thing and return a SignalResult."""
        ...

    def run(
        self, query: str, answer: str, evidence: list[EvidenceItem]
    ) -> SignalResult:
        """Safe wrapper around score(): never raises, always times itself."""
        start = time.perf_counter()
        try:
            result = self.score(query, answer, evidence)
            if not isinstance(result, SignalResult):
                raise TypeError(
                    f"score() must return SignalResult, got {type(result).__name__}"
                )
        except Exception as exc:
            logger.exception("Signal %s failed", self.name)
            result = SignalResult(
                value=None,
                reasons=[
                    Reason(
                        code=ReasonCode.SIGNAL_UNAVAILABLE,
                        message=f"The {self.name} signal could not be computed ({type(exc).__name__}).",
                    )
                ],
                details={"error_type": type(exc).__name__},
            )
        result.details["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        return result
        