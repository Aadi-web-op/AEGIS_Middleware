from app.evidence.ambiguity import AmbiguitySignal
from app.schemas import EvidenceItem, ReasonCode


def test_clear_query_has_low_ambiguity():
    result = AmbiguitySignal().run(
        query="What is the capital of France?",
        answer="Paris.",
        evidence=[],
    )

    assert result.value == 0.0
    assert result.reasons == []


def test_short_query_is_ambiguous():
    result = AmbiguitySignal().run(
        query="Why?",
        answer="Because of the policy.",
        evidence=[],
    )

    assert result.value == 0.5
    assert result.reasons[0].code == ReasonCode.AMBIGUOUS_QUERY


def test_multiple_generic_terms_increase_ambiguity():
    result = AmbiguitySignal().run(
        query="Why does it affect them?",
        answer="It affects them because of the policy.",
        evidence=[],
    )

    assert result.value == 0.3
    assert result.reasons[0].code == ReasonCode.AMBIGUOUS_QUERY


def test_empty_query_is_highly_ambiguous():
    result = AmbiguitySignal().run(
        query="",
        answer="I cannot answer this.",
        evidence=[],
    )

    assert result.value == 1.0
    assert result.reasons[0].code == ReasonCode.AMBIGUOUS_QUERY


def test_ambiguity_value_stays_between_zero_and_one():
    result = AmbiguitySignal().run(
        query="Why does it affect them?",
        answer="Some answer.",
        evidence=[],
    )

    assert 0.0 <= result.value <= 1.0
