"""Thresholds and severity boundaries in app.intelligence.rules."""

from __future__ import annotations

import pytest

from app.intelligence import rules
from app.intelligence.models import finding_id


def test_contract_minimums():
    assert rules.MIN_DECISIONS_FOR_FINDING == 2
    assert rules.MIN_GRAPH_DECISIONS == 5
    assert rules.MAX_REQUEST_IDS == 20


@pytest.mark.parametrize("n,expected", [(0, False), (1, False), (2, True), (7, True)])
def test_is_recurring_boundary(n, expected):
    assert rules.is_recurring(n) is expected


def test_rate_handles_empty_denominator_and_rounds():
    assert rules.rate(0, 0) == 0.0
    assert rules.rate(2, 3) == 0.6667
    assert rules.rate(4, 4) == 1.0


def test_cap_never_raises_severity():
    assert rules.cap(rules.HIGH, rules.MEDIUM) == rules.MEDIUM
    assert rules.cap(rules.LOW, rules.MEDIUM) == rules.LOW
    assert rules.cap(rules.MEDIUM, rules.MEDIUM) == rules.MEDIUM


def test_severity_rank_orders_high_first():
    assert rules.severity_rank("high") < rules.severity_rank("medium") < rules.severity_rank("low")


@pytest.mark.parametrize(
    "decisions,rate_,expected",
    [(2, 0.2, "medium"), (3, 0.2, "high"), (2, 0.5, "high"), (2, 0.49, "medium")],
)
def test_unsupported_direct_severity(decisions, rate_, expected):
    assert rules.unsupported_direct_severity(decisions, rate_) == expected


@pytest.mark.parametrize(
    "decisions,rate_,expected",
    [(5, 0.49, None), (2, 0.5, "low"), (2, 0.9, "low"), (3, 0.74, "low"), (3, 0.75, "medium")],
)
def test_unsupported_considered_severity_is_capped(decisions, rate_, expected):
    assert rules.unsupported_considered_severity(decisions, rate_) == expected
    # Considered attribution can never be high, however strong the numbers.
    assert rules.unsupported_considered_severity(100, 1.0) == rules.CONSIDERED_SEVERITY_CAP


def test_contradiction_severity():
    assert rules.contradiction_severity(2, ["statement"], ["ESCALATE", "ESCALATE"]) == "medium"
    assert rules.contradiction_severity(3, ["statement"], ["ESCALATE"]) == "high"
    # numeric conflict that still reached the user
    assert rules.contradiction_severity(2, ["numeric"], ["ESCALATE", "CAVEAT"]) == "high"
    # numeric conflict, but nothing was shown
    assert rules.contradiction_severity(2, ["date"], ["ABSTAIN", "ESCALATE"]) == "medium"
    # a shown answer with a non-value conflict kind stays medium
    assert rules.contradiction_severity(2, ["version"], ["ANSWER", "ANSWER"]) == "medium"


def test_stale_severity():
    assert rules.stale_severity(2, 0) == "medium"
    assert rules.stale_severity(3, 0) == "high"
    assert rules.stale_severity(2, 1) == "high"


@pytest.mark.parametrize(
    "decisions,rate_,expected",
    [(4, 0.49, None), (2, 0.5, "medium"), (2, 1.0, "medium"), (3, 0.79, "medium"), (3, 0.8, "high")],
)
def test_knowledge_gap_severity(decisions, rate_, expected):
    assert rules.knowledge_gap_severity(decisions, rate_) == expected


def test_root_cause_severity():
    assert rules.root_cause_severity(2, 0.4) == "medium"
    assert rules.root_cause_severity(2, 0.5) == "high"
    assert rules.root_cause_severity(3, 0.1) == "high"


@pytest.mark.parametrize("share,expected", [(0.29, None), (0.3, "medium"), (0.59, "medium"), (0.6, "high")])
def test_uncertainty_severity(share, expected):
    assert rules.uncertainty_severity(share) == expected


def test_finding_id_is_stable_and_order_independent():
    a = finding_id("contradiction_hotspot", "doc:a", "doc:b")
    assert a == finding_id("contradiction_hotspot", "doc:b", "doc:a")
    assert a != finding_id("stale_version_in_use", "doc:a", "doc:b")
    assert len(a) == 16
