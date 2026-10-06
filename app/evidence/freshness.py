from datetime import date

from app.evidence.base import Signal
from app.schemas import EvidenceItem, Reason, ReasonCode, SignalResult


class FreshnessSignal(Signal):
    """Measure how recent the available evidence is."""

    name = "freshness"

    def score(
        self,
        query: str,
        answer: str,
        evidence: list[EvidenceItem],
    ) -> SignalResult:
        dated_evidence = [item for item in evidence if item.date is not None]

        if not dated_evidence:
            return SignalResult(
                value=None,
                reasons=[
                    Reason(
                        code=ReasonCode.SIGNAL_UNAVAILABLE,
                        message="Evidence dates are unavailable, so freshness could not be determined.",
                    )
                ],
                details={"dated_evidence": 0, "total_evidence": len(evidence)},
            )

        today = date.today()

        ages = [
            max(0, (today - item.date).days)
            for item in dated_evidence
        ]

        average_age = sum(ages) / len(ages)

        # Simple decay:
        # 0 days old -> 1.0
        # 30 days old -> 0.5
        # 90+ days old -> approaches 0
        freshness = max(0.0, 1.0 - (average_age / 90.0))

        return SignalResult(
            value=round(freshness, 4),
            reasons=[],
            details={
                "dated_evidence": len(dated_evidence),
                "total_evidence": len(evidence),
                "average_age_days": round(average_age, 2),
                "max_age_days": max(ages),
            },
        )