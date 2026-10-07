"""Unit tests for claim extraction and query decomposition.

Pure-Python, no model download required.
"""

from aegis_core.signals.entailment import extract_claims
from aegis_core.signals.completeness import decompose_query


# ------------------------------------------------------------------
# claim extraction
# ------------------------------------------------------------------
def test_extract_single_claim():
    claims = extract_claims("Employees receive 18 casual leaves per year.")
    assert len(claims) == 1
    assert "18" in claims[0]


def test_extract_multiple_claims():
    answer = (
        "Full-time employees get 18 casual leaves. "
        "Part-time employees get 10 casual leaves. "
        "Sick leave is separate."
    )
    claims = extract_claims(answer)
    assert len(claims) == 3


def test_filler_sentence_dropped():
    claims = extract_claims("Here is the answer. Employees get 18 leaves per year.")
    assert len(claims) == 1
    assert "18" in claims[0]


def test_short_fragment_dropped():
    claims = extract_claims("OK. Employees receive 18 casual leaves per year.")
    assert all(len(c) > 15 for c in claims)


def test_empty_answer_no_claims():
    assert extract_claims("") == []
    assert extract_claims(None) == []


def test_max_claims_respected():
    answer = ". ".join(f"Claim number {i} is about something important." for i in range(20))
    claims = extract_claims(answer, max_claims=5)
    assert len(claims) == 5


# ------------------------------------------------------------------
# query decomposition
# ------------------------------------------------------------------
def test_decompose_single_aspect():
    aspects = decompose_query("How many casual leaves can an employee take?")
    assert len(aspects) == 1


def test_decompose_two_aspects():
    aspects = decompose_query(
        "What is the refund period and does it apply to contractors?"
    )
    assert len(aspects) == 2


def test_decompose_keeps_interrogative():
    aspects = decompose_query(
        "What is the refund period and does it apply to contractors?"
    )
    # Second aspect should retain the question stem so it can be
    # matched against evidence.
    joined = " ".join(aspects).lower()
    assert "does" in joined or "what" in joined


def test_decompose_or_split():
    aspects = decompose_query("Does it cover laptops or desktops?")
    assert len(aspects) == 2


def test_decompose_empty():
    assert decompose_query("") == []
    assert decompose_query(None) == []


def test_decompose_max_aspects():
    aspects = decompose_query("a and b and c and d and e and f and g", max_aspects=4)
    assert len(aspects) <= 4
