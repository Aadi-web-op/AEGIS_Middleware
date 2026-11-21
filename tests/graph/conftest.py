"""A canonical trace, built from real signal output rather than by hand.

The trace used across the graph tests comes out of the actual entailment
and contradiction signals (with a faked NLI runner for determinism) and
through the trace builder, so these tests check that conflict kinds,
detected values and evidence indices survive the whole path from signal
to Cypher -- not just that a hand-written dict round-trips.
"""

from __future__ import annotations

import pytest

from aegis_core.signals.contradiction import ContradictionSignal
from aegis_core.signals.entailment import EntailmentSignal
from app.graph.trace_builder import build_trace
from tests.conftest import FakeNLI

REQUEST_ID = "req-canonical-0001"

LEAVE_18 = "Full-time employees are entitled to 18 casual leaves per year."
LEAVE_12 = "Employees are entitled to 12 casual leaves per year."
ANSWER = "Employees receive 18 casual leaves."

# A passage comfortably longer than the 120-character preview cap.
LONG_PASSAGE = (
    "Casual leave entitlement is reviewed annually by the human resources "
    "committee, which publishes the revised allowance in the staff handbook "
    "together with the carry-over rules, the approval workflow and the "
    "notice period expected before a leave request is submitted."
)

EVIDENCE = [
    {
        "text": LEAVE_18,
        "source": "hr-policy.pdf",
        "version": "2023.1",
        "date": "2023-04-01",
    },
    {
        "text": LEAVE_12,
        "source": "hr-policy.pdf",
        "version": "2024.2",
        "date": "2024-04-01",
    },
    {
        "text": LONG_PASSAGE,
        "source": "staff-handbook.pdf",
        "version": "7",
        "date": "2024-01-15",
    },
]

REASONS = [
    {"code": "CONTRADICTION", "message": "Two policy passages disagree."},
    {"code": "UNSUPPORTED_CLAIM", "message": "One claim is not fully supported."},
]


@pytest.fixture(scope="session")
def signal_details():
    """Entailment and contradiction details for the canonical case."""
    texts = [item["text"] for item in EVIDENCE]
    metadata = [
        {"source": i["source"], "version": i["version"], "date": i["date"]}
        for i in EVIDENCE
    ]

    entailment = EntailmentSignal()
    entailment.nli = FakeNLI(
        {
            (LEAVE_18, ANSWER): (0.91, 0.02, 0.07),
            (LEAVE_12, ANSWER): (0.02, 0.88, 0.10),
        }
    )
    contradiction = ContradictionSignal()
    contradiction.nli = FakeNLI()

    return {
        "entailment": entailment.evaluate(
            "How many casual leaves?", ANSWER, list(texts)
        ).details,
        "contradiction": contradiction.evaluate(
            "How many casual leaves?",
            ANSWER,
            list(texts),
            evidence_metadata=metadata,
        ).details,
    }


@pytest.fixture
def trace(signal_details):
    """The canonical trace: ESCALATE on disagreeing policy versions."""
    return build_trace(
        request_id=REQUEST_ID,
        decision="ESCALATE",
        headline="Two versions of the leave policy disagree on the allowance.",
        evidence=EVIDENCE,
        entailment_details=signal_details["entailment"],
        contradiction_details=signal_details["contradiction"],
        reasons=REASONS,
        answerability_score=0.41,
        policy_version="0.1.0",
        profile="standard",
    )
