import pytest
from pydantic import ValidationError

from app.schemas import (
    Decision,
    EvaluateRequest,
    EvaluateResponse,
    ReasonCode,
    RecommendedAction,
    SignalResult,
    Signals,
)


def test_valid_request_parses():
    req = EvaluateRequest(
        query="How many casual leaves?",
        answer="18.",
        evidence=[{"text": "18 casual leaves.", "source": "policy.pdf", "date": "2026-08-01"}],
    )
    assert len(req.evidence) == 1
    assert req.evidence[0].date.year == 2026


def test_empty_evidence_is_allowed():
    req = EvaluateRequest(query="Q?", answer="A.")
    assert req.evidence == []


def test_empty_query_is_rejected():
    with pytest.raises(ValidationError):
        EvaluateRequest(query="", answer="A.")


def test_profile_defaults_to_standard():
    req = EvaluateRequest(query="Q?", answer="A.")
    assert req.profile == "standard"


def test_signal_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        Signals(relevance=1.7)


def test_signals_may_be_unavailable():
    assert Signals().relevance is None


def test_signal_result_can_be_unavailable():
    r = SignalResult()
    assert r.value is None and r.reasons == [] and r.details == {}


def test_decision_labels_match_plan():
    assert {d.value for d in Decision} == {"ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"}


def test_response_gets_unique_request_ids():
    def make():
        return EvaluateResponse(
            decision=Decision.ABSTAIN,
            answerability_score=0.0,
            signals=Signals(),
            recommended_action=RecommendedAction.ABSTAIN,
        )
    assert make().request_id != make().request_id


def test_reason_code_is_plain_string():
    assert ReasonCode.CONTRADICTION.value == "CONTRADICTION"


def test_time_sensitive_defaults_to_true():
    assert EvaluateRequest(query="Q?", answer="A.").time_sensitive is True

    