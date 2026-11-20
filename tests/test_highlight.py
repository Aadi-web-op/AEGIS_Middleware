"""Sentence-level evidence highlighting (app/evidence/highlight.py)."""

from app.evidence.highlight import build_highlights, split_sentences
from app.schemas import (
    ClaimResult,
    ClaimStatus,
    Decision,
    EvaluateRequest,
    EvaluateResponse,
    RecommendedAction,
    Signals,
)

POLICY = (
    "Full-time employees are entitled to 12 days of paid annual leave per year. "
    "Leave requests must be approved by a manager."
)
CARRY = "Up to 5 unused leave days may be carried over to the next year."


def _response(claims):
    return EvaluateResponse(
        decision=Decision.ESCALATE,
        answerability_score=0.5,
        signals=Signals(),
        claims=claims,
        recommended_action=RecommendedAction.ESCALATE_TO_HUMAN,
    )


def _request(*texts):
    return EvaluateRequest(
        query="How much leave?",
        answer="x",
        evidence=[{"text": t, "source": "leave_policy.pdf", "version": "2024"} for t in texts],
    )


def test_split_sentences_keeps_decimals_and_trims():
    text = "  Rate is 2.5 days.  Second one!\nThird"
    parts = [text[s:e] for s, e in split_sentences(text)]
    assert parts == ["Rate is 2.5 days.", "Second one!", "Third"]


def test_split_sentences_empty():
    assert split_sentences("   ") == []


def test_conflict_points_at_sentence_and_marks_number():
    claim = ClaimResult(
        claim="Employees get 18 days of annual leave per year.",
        status=ClaimStatus.CONTRADICTED,
        support=0.07,
        contradicting_evidence_indices=[0],
    )
    [highlight] = build_highlights(_request(POLICY), _response([claim]))
    [span] = highlight.spans
    assert span.kind == "conflict"
    assert POLICY[span.start:span.end].startswith("Full-time employees")
    assert POLICY[span.start:span.end].endswith("per year.")
    [mark] = highlight.numbers
    assert POLICY[mark.start:mark.end] == "12 days"
    assert mark.claim_value == "18 days"


def test_support_span_and_no_number_marks():
    claim = ClaimResult(
        claim="Unused leave can be carried over.",
        status=ClaimStatus.SUPPORTED,
        support=0.98,
        supporting_evidence_indices=[1],
    )
    highlights = build_highlights(_request(POLICY, CARRY), _response([claim]))
    assert [h.evidence_index for h in highlights] == [1]
    assert highlights[0].spans[0].kind == "support"
    assert highlights[0].numbers == []
    assert highlights[0].source == "leave_policy.pdf"


def test_out_of_range_indices_and_no_claims_are_ignored():
    claim = ClaimResult(
        claim="Anything.", status=ClaimStatus.UNSUPPORTED, support=0.0,
        supporting_evidence_indices=[7], contradicting_evidence_indices=[-1],
    )
    assert build_highlights(_request(POLICY), _response([claim])) == []
    assert build_highlights(_request(), _response([])) == []
