from datetime import date, timedelta

from app.evidence.freshness import FreshnessSignal
from app.schemas import EvidenceItem, ReasonCode


def test_freshness_recent_evidence():
    evidence = [
        EvidenceItem(
            text="Recent information.",
            source="test.pdf",
            date=date.today(),
        )
    ]

    result = FreshnessSignal().run(
        query="What happened?",
        answer="Recent information.",
        evidence=evidence,
    )

    assert result.value == 1.0
    assert result.details["dated_evidence"] == 1
    assert result.details["average_age_days"] == 0


def test_freshness_old_evidence():
    evidence = [
        EvidenceItem(
            text="Old information.",
            source="test.pdf",
            date=date.today() - timedelta(days=90),
        )
    ]

    result = FreshnessSignal().run(
        query="What happened?",
        answer="Old information.",
        evidence=evidence,
    )

    assert result.value == 0.0
    assert result.details["average_age_days"] == 90


def test_freshness_missing_dates():
    evidence = [
        EvidenceItem(
            text="Information without a date.",
            source="test.pdf",
        )
    ]

    result = FreshnessSignal().run(
        query="What happened?",
        answer="Information without a date.",
        evidence=evidence,
    )

    assert result.value is None
    assert result.reasons[0].code == ReasonCode.SIGNAL_UNAVAILABLE


def test_freshness_mixed_dates():
    evidence = [
        EvidenceItem(
            text="Recent information.",
            source="recent.pdf",
            date=date.today(),
        ),
        EvidenceItem(
            text="Older information.",
            source="old.pdf",
            date=date.today() - timedelta(days=30),
        ),
    ]

    result = FreshnessSignal().run(
        query="What happened?",
        answer="Information.",
        evidence=evidence,
    )

    assert result.value == 0.8333
    assert result.details["dated_evidence"] == 2
    assert result.details["average_age_days"] == 15