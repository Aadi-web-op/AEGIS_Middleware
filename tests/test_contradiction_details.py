"""Conflict-level contradiction detail: pairs, kinds and detected values.

Covers the canonical "18 versus 12 casual leaves" case both as an
answer-versus-evidence conflict and as an evidence-versus-evidence one,
plus the rule that a conflict without a reliable source pair is reported
as a diagnostic but marked ineligible for a graph edge.

The NLI runner is faked so that numeric and date rules are tested in
isolation from model behaviour; `default=(0.1, 0.1, 0.8)` means "no
statement-level contradiction unless a test says so".
"""

import pytest

from aegis_core.signals.contradiction import ContradictionSignal
from tests.conftest import BrokenNLI, FakeNLI

LEAVE_18 = "Employees are entitled to 18 casual leaves per year."
LEAVE_12 = "Employees are entitled to 12 casual leaves per year."
SICK_12 = "Sick leave allowance is 12 sick leaves per year."
ANSWER_18 = "Employees receive 18 casual leaves."


def _signal(table=None, **kwargs):
    signal = ContradictionSignal(**kwargs)
    signal.nli = FakeNLI(table)
    return signal


def _conflicts(result, kind=None, scope=None):
    out = result.details["conflicts"]
    if kind:
        out = [c for c in out if c["kind"] == kind]
    if scope:
        out = [c for c in out if c["scope"] == scope]
    return out


# ---------------------------------------------------------------------------
# the canonical 18-versus-12 case
# ---------------------------------------------------------------------------
def test_18_versus_12_between_two_evidence_passages():
    result = _signal().evaluate(
        "How many casual leaves?", ANSWER_18, [LEAVE_18, LEAVE_12]
    )

    conflicts = _conflicts(result, kind="numeric", scope="evidence_vs_evidence")
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["evidence_indices"] == [0, 1]
    assert conflict["index_a"] == 0
    assert conflict["index_b"] == 1
    assert conflict["value_a"] == "18"
    assert conflict["value_b"] == "12"
    assert conflict["graph_edge_eligible"] is True
    assert "18" in conflict["reason"] and "12" in conflict["reason"]


def test_18_versus_12_between_answer_and_evidence_has_one_index_only():
    """The answer is not an evidence passage, so no pair edge is eligible."""
    result = _signal().evaluate("How many casual leaves?", ANSWER_18, [LEAVE_12])

    conflicts = _conflicts(result, kind="numeric", scope="answer_vs_evidence")
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["index_a"] is None
    assert conflict["index_b"] == 0
    assert conflict["evidence_indices"] == [0]
    assert conflict["value_a"] == "18"
    assert conflict["value_b"] == "12"
    # Reported as a diagnostic, but the graph must omit the edge.
    assert conflict["graph_edge_eligible"] is False


def test_detected_values_are_rendered_without_float_noise():
    result = _signal().evaluate("q", ANSWER_18, [LEAVE_18, LEAVE_12])
    conflict = _conflicts(result, kind="numeric", scope="evidence_vs_evidence")[0]
    assert conflict["value_a"] == "18"
    assert conflict["value_b"] == "12"


def test_source_and_version_identifiers_come_from_metadata():
    result = _signal().evaluate(
        "q",
        ANSWER_18,
        [LEAVE_18, LEAVE_12],
        evidence_metadata=[
            {"source": "hr-2023.pdf", "version": "2023", "date": "2023-01-01"},
            {"source": "hr-2024.pdf", "version": "2024", "date": "2024-01-01"},
        ],
    )
    conflict = _conflicts(result, kind="numeric", scope="evidence_vs_evidence")[0]
    assert conflict["source_a"] == "hr-2023.pdf"
    assert conflict["source_b"] == "hr-2024.pdf"
    assert conflict["version_a"] == "2023"
    assert conflict["version_b"] == "2024"


# ---------------------------------------------------------------------------
# other conflict kinds
# ---------------------------------------------------------------------------
def test_statement_conflict_carries_indices_but_no_scalar_values():
    table = {(LEAVE_18, LEAVE_12): (0.02, 0.95, 0.03)}
    result = _signal(table).evaluate("q", "", [LEAVE_18, LEAVE_12])

    statements = _conflicts(result, kind="statement")
    assert len(statements) == 1
    conflict = statements[0]
    assert conflict["evidence_indices"] == [0, 1]
    assert conflict["value_a"] is None
    assert conflict["value_b"] is None
    assert conflict["graph_edge_eligible"] is True
    assert "contradict" in conflict["reason"]


def test_date_conflict_reports_both_dates():
    early = "The policy takes effect on January 1, 2024."
    late = "The updated policy is effective from March 15, 2024."
    result = _signal().evaluate("q", "", [early, late])

    dates = _conflicts(result, kind="date", scope="evidence_vs_evidence")
    assert dates, "a January/March mismatch should be detected"
    conflict = dates[0]
    assert conflict["evidence_indices"] == [0, 1]
    assert conflict["value_a"] == "2024-01-01"
    assert conflict["value_b"] == "2024-03-15"
    assert conflict["graph_edge_eligible"] is True


def test_version_conflict_reports_versions_and_pair():
    result = _signal().evaluate(
        "q",
        "",
        [LEAVE_18, LEAVE_12],
        evidence_metadata=[
            {"source": "hr.pdf", "version": "2023"},
            {"source": "hr.pdf", "version": "2024"},
        ],
    )
    versions = _conflicts(result, kind="version")
    assert len(versions) == 1
    conflict = versions[0]
    assert conflict["evidence_indices"] == [0, 1]
    assert conflict["value_a"] == "2023"
    assert conflict["value_b"] == "2024"
    assert conflict["graph_edge_eligible"] is True


# ---------------------------------------------------------------------------
# restraint
# ---------------------------------------------------------------------------
def test_wording_differences_alone_are_not_conflicts():
    paraphrase_a = "Employees are entitled to 18 casual leaves per year."
    paraphrase_b = "Each employee receives 18 casual leaves annually."
    result = _signal().evaluate("q", "", [paraphrase_a, paraphrase_b])

    assert result.details["conflicts"] == []
    assert result.value == 0.0


def test_different_head_nouns_are_not_compared():
    """18 casual leaves versus 12 sick leaves is not a conflict."""
    result = _signal().evaluate("q", "", [LEAVE_18, SICK_12])
    assert _conflicts(result, kind="numeric") == []


def test_no_evidence_still_exposes_the_conflicts_key():
    result = _signal().evaluate("q", ANSWER_18, [])
    assert result.details["conflicts"] == []
    assert result.details["checkable"] is False


def test_broken_nli_currently_disables_rule_based_conflicts_too():
    """Documents a pre-existing defect, unchanged by the graph add-on.

    `_check_answer_vs_evidence` and `_check_evidence_vs_evidence` call
    `find_numeric_conflicts` / `find_date_conflicts` from *inside* their
    `zip(..., preds)` loop. When the NLI model is unavailable `preds` is
    `[]`, the zip is empty, and the pure-Python numeric and date rules --
    which need no model at all -- never run. The signal reports 0.0.

    This is on `origin/main` and is asserted here as-is rather than
    fixed, because moving it would change the contradiction score on the
    degraded path and so change decisions. See the note for Aaradhya in
    `docs/decision-graph-proposal.md`.
    """
    signal = ContradictionSignal()
    signal.nli = BrokenNLI()
    result = signal.evaluate("q", ANSWER_18, [LEAVE_18, LEAVE_12])

    assert result.details["conflicts"] == []
    assert result.value == 0.0

    # The rules themselves are fine; only the wiring above skips them.
    from aegis_core.utils.numeric_date import find_numeric_conflicts

    assert find_numeric_conflicts(LEAVE_18, LEAVE_12), (
        "the numeric rule detects 18 vs 12 on its own, so the gap above is "
        "in how the signal calls it, not in the rule"
    )


def test_duplicate_findings_are_not_reported_twice():
    result = _signal().evaluate("q", "", [LEAVE_18, LEAVE_12])
    keys = [
        (c["kind"], c["scope"], tuple(c["evidence_indices"]), c["value_a"], c["value_b"])
        for c in result.details["conflicts"]
    ]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# the score must not move
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "answer, evidence, metadata",
    [
        (ANSWER_18, [LEAVE_18, LEAVE_12], None),
        (ANSWER_18, [LEAVE_12], None),
        ("", [LEAVE_18, LEAVE_12], [{"version": "1"}, {"version": "2"}]),
        (ANSWER_18, [LEAVE_18], None),
    ],
)
def test_projection_does_not_change_the_contradiction_score(answer, evidence, metadata):
    """The projection reads findings after scoring; it must not feed back in.

    Recomputing the score from the untouched scoring inputs must match the
    reported value exactly -- and a high value still means "more
    contradiction", not the inverse.
    """
    signal = _signal()
    result = signal.evaluate("q", answer, list(evidence), evidence_metadata=metadata)

    answer_conflicts, answer_numeric, answer_dates = signal._check_answer_vs_evidence(
        answer, list(evidence)
    )
    ev_conflicts, ev_numeric, ev_dates = signal._check_evidence_vs_evidence(
        list(evidence)
    )
    version_conflicts = signal._check_version_metadata(list(evidence), metadata or [])
    expected = signal._score_contradiction(
        answer_conflicts + ev_conflicts + version_conflicts,
        answer_numeric + ev_numeric,
        answer_dates + ev_dates,
        len(evidence),
    )
    assert result.value == expected


def test_existing_detail_keys_are_preserved():
    result = _signal().evaluate("q", ANSWER_18, [LEAVE_18, LEAVE_12])
    for key in (
        "contradiction_score",
        "answer_vs_evidence_conflicts",
        "evidence_vs_evidence_conflicts",
        "version_conflicts",
        "conflicting_pairs",
        "numeric_mismatches",
        "date_mismatches",
        "evidence_count",
        "checkable",
    ):
        assert key in result.details, key
    assert result.details["numeric_mismatches"][0]["kind"] == "numeric"
