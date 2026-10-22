"""Claim-level entailment detail: status, support and evidence indices.

Deterministic -- the NLI runner is replaced with a fake, so the asserted
indices follow from stated probabilities rather than from a model
download. The signal's own value and reason strings are checked to be
unchanged by the added detail.
"""

from aegis_core.signals.entailment import EntailmentSignal
from tests.conftest import BrokenNLI, FakeNLI

LEAVE_18 = "Full-time employees are entitled to 18 casual leaves per year."
LEAVE_12 = "Employees are entitled to 12 casual leaves per year."
CAFETERIA = "The cafeteria serves lunch from 12 PM to 2 PM every weekday."
ANSWER = "Employees receive 18 casual leaves."


def _signal(table, **kwargs):
    signal = EntailmentSignal(**kwargs)
    signal.nli = FakeNLI(table)
    return signal


def test_supported_claim_names_its_supporting_index():
    signal = _signal({(LEAVE_18, ANSWER): (0.92, 0.02, 0.06)})
    result = signal.evaluate("How many casual leaves?", ANSWER, [LEAVE_18])

    claim = result.details["claims"][0]
    assert claim["claim_index"] == 0
    assert claim["claim"] == ANSWER
    assert claim["status"] == "SUPPORTED"
    assert claim["support"] == 0.92
    assert claim["supporting_evidence_indices"] == [0]
    assert claim["contradicting_evidence_indices"] == []
    assert claim["evidence_indices"] == [0]
    assert claim["nli_available"] is True


def test_contradicted_claim_names_its_contradicting_index():
    signal = _signal({(LEAVE_12, ANSWER): (0.03, 0.91, 0.06)})
    result = signal.evaluate("How many casual leaves?", ANSWER, [LEAVE_12])

    claim = result.details["claims"][0]
    assert claim["status"] == "CONTRADICTED"
    assert claim["supporting_evidence_indices"] == []
    assert claim["contradicting_evidence_indices"] == [0]
    assert any("Contradicted by evidence [0]" in r for r in claim["reasons"])


def test_unsupported_claim_names_no_index_at_all():
    """A neutral claim must not borrow an index it was not given."""
    signal = _signal({(CAFETERIA, ANSWER): (0.05, 0.05, 0.90)})
    result = signal.evaluate("How many casual leaves?", ANSWER, [CAFETERIA])

    claim = result.details["claims"][0]
    assert claim["status"] == "UNSUPPORTED"
    assert claim["supporting_evidence_indices"] == []
    assert claim["contradicting_evidence_indices"] == []
    assert claim["evidence_indices"] == []
    # The legacy text field keeps its original fallback behaviour...
    assert claim["evidence"] == [CAFETERIA]
    # ...but that must never leak into an index.
    assert claim["evidence_indices"] == []


def test_indices_are_positions_in_the_supplied_evidence_list():
    signal = _signal({(LEAVE_18, ANSWER): (0.88, 0.02, 0.10)})
    result = signal.evaluate(
        "How many casual leaves?", ANSWER, [CAFETERIA, LEAVE_18, LEAVE_12]
    )

    claim = result.details["claims"][0]
    assert claim["supporting_evidence_indices"] == [1]
    assert result.details["evidence_considered"] == 3
    assert result.details["evidence_supplied"] == 3
    assert result.details["evidence_truncated"] is False


def test_disagreeing_sources_populate_both_index_lists():
    """One passage entails the claim, another contradicts it."""
    signal = _signal(
        {
            (LEAVE_18, ANSWER): (0.90, 0.03, 0.07),
            (LEAVE_12, ANSWER): (0.02, 0.89, 0.09),
        }
    )
    result = signal.evaluate("How many casual leaves?", ANSWER, [LEAVE_18, LEAVE_12])

    claim = result.details["claims"][0]
    assert claim["supporting_evidence_indices"] == [0]
    assert claim["contradicting_evidence_indices"] == [1]
    assert claim["evidence_indices"] == [0, 1]
    # Entailment still outranks contradiction for the label, as before.
    assert claim["label"] == "ENTAILMENT"
    assert claim["status"] == "SUPPORTED"
    assert any("sources disagree" in r for r in claim["reasons"])


def test_multiple_claims_keep_their_own_indices():
    first = "Full-time employees get 18 casual leaves per year."
    second = "Sick leave allowance is 12 days per year."
    answer = f"{first} {second}"
    sick = "Sick leave allowance is 12 days per year."

    signal = _signal(
        {
            (LEAVE_18, first): (0.93, 0.02, 0.05),
            (sick, second): (0.95, 0.01, 0.04),
        }
    )
    result = signal.evaluate("Leave policy?", answer, [LEAVE_18, sick])

    claims = result.details["claims"]
    assert [c["claim_index"] for c in claims] == [0, 1]
    assert claims[0]["supporting_evidence_indices"] == [0]
    assert claims[1]["supporting_evidence_indices"] == [1]


def test_truncation_is_reported_so_absent_indices_are_not_a_finding():
    signal = _signal({}, max_evidence_per_claim=2)
    result = signal.evaluate(
        "How many casual leaves?", ANSWER, [CAFETERIA, LEAVE_18, LEAVE_12]
    )

    assert result.details["evidence_considered"] == 2
    assert result.details["evidence_supplied"] == 3
    assert result.details["evidence_truncated"] is True


def test_unavailable_model_is_reported_rather_than_guessed():
    signal = EntailmentSignal()
    signal.nli = BrokenNLI()
    result = signal.evaluate("How many casual leaves?", ANSWER, [LEAVE_18])

    claim = result.details["claims"][0]
    assert claim["nli_available"] is False
    assert claim["supporting_evidence_indices"] == []
    assert claim["contradicting_evidence_indices"] == []
    assert claim["reasons"] == [
        "NLI model unavailable; this claim could not be verified."
    ]


def test_added_detail_does_not_move_the_signal_value_or_reasons():
    """The policy interface -- value and reasons -- is unchanged."""
    table = {
        (LEAVE_18, ANSWER): (0.90, 0.03, 0.07),
        (LEAVE_12, ANSWER): (0.02, 0.89, 0.09),
    }
    result = _signal(table).evaluate(
        "How many casual leaves?", ANSWER, [LEAVE_18, LEAVE_12]
    )

    assert result.value == 0.90
    assert result.details["support_score"] == 0.90
    assert result.reasons == [
        "Strong support: 1/1 claims entailed by evidence"
    ]


def test_no_evidence_and_no_claims_keep_their_existing_shape():
    signal = _signal({})
    empty_evidence = signal.evaluate("q", ANSWER, [])
    assert empty_evidence.value == 0.0
    assert empty_evidence.details["claims"] == []

    no_claims = signal.evaluate("q", "Here is the answer.", [LEAVE_18])
    assert no_claims.value == 0.5
    assert no_claims.details["claims"] == []
