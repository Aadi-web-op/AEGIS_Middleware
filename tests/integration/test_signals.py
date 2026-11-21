"""Integration tests for the evidence signals.

These tests load the real models (once per session via fixtures in
conftest.py). Assertions use threshold ranges, never exact floats.
"""

# ------------------------------------------------------------------
# RELEVANCE
# ------------------------------------------------------------------
def test_relevance_direct_match(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
    )
    rel = r.signals["relevance"]["value"]
    assert rel > 0.7, f"direct match should be highly relevant, got {rel}"


def test_relevance_paraphrase(evidence_engine):
    r = evidence_engine.evaluate(
        query="What is the casual leave policy for employees?",
        answer="Staff members get 18 days of casual leave annually.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
    )
    rel = r.signals["relevance"]["value"]
    assert rel > 0.6, f"paraphrase should still be relevant, got {rel}"


def test_relevance_unrelated(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["The cafeteria serves lunch from 12 PM to 2 PM."],
    )
    rel = r.signals["relevance"]["value"]
    assert rel < 0.2, f"unrelated evidence should have low relevance, got {rel}"


# ------------------------------------------------------------------
# ENTAILMENT / SUPPORT
# ------------------------------------------------------------------
def test_entailment_supported(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
    )
    ent = r.signals["entailment"]["value"]
    assert ent > 0.7, f"supported claim should score high, got {ent}"


def test_entailment_contradicted(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 12 casual leaves per year."],
    )
    ent = r.signals["entailment"]["value"]
    assert ent < 0.4, f"contradicted claim should score low, got {ent}"


def test_entailment_neutral(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["The cafeteria serves lunch from 12 PM to 2 PM."],
    )
    ent = r.signals["entailment"]["value"]
    assert ent < 0.6, f"unrelated evidence yields neutral/low support, got {ent}"


def test_entailment_multiple_claims(evidence_engine):
    r = evidence_engine.evaluate(
        query="Leave policy?",
        answer=(
            "Full-time employees get 18 casual leaves per year. "
            "Sick leave allowance is 12 days per year."
        ),
        evidence=[
            "Full-time employees are entitled to 18 casual leaves per year.",
            "Sick leave allowance is 12 days per year.",
        ],
    )
    ent = r.signals["entailment"]["value"]
    details = r.signals["entailment"]["details"]
    assert ent > 0.7, f"both claims supported, got {ent}"
    assert details["claim_count"] == 2
    labels = [c["label"] for c in details["claims"]]
    assert labels.count("ENTAILMENT") == 2


# ------------------------------------------------------------------
# CONTRADICTION
# ------------------------------------------------------------------
def test_contradiction_answer_vs_evidence(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 12 casual leaves per year."],
    )
    con = r.signals["contradiction"]["value"]
    assert con > 0.5, f"answer/evidence conflict expected, got {con}"


def test_contradiction_evidence_vs_evidence(evidence_engine):
    r = evidence_engine.evaluate(
        query="What is the refund period?",
        answer="Refunds are available within 30 days.",
        evidence=[
            "Refund requests must be made within 30 days of purchase.",
            "Refund requests must be made within 45 days of purchase.",
        ],
    )
    con = r.signals["contradiction"]["value"]
    assert con > 0.5, f"evidence/evidence conflict expected, got {con}"


def test_contradiction_numeric_mismatch(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 12 casual leaves per year."],
    )
    mismatches = r.signals["contradiction"]["details"]["numeric_mismatches"]
    assert len(mismatches) >= 1
    assert mismatches[0]["kind"] == "numeric"


def test_contradiction_date_mismatch(evidence_engine):
    r = evidence_engine.evaluate(
        query="When does the policy take effect?",
        answer="The policy takes effect on January 1, 2024.",
        evidence=["The updated policy is effective from March 15, 2024."],
    )
    mismatches = r.signals["contradiction"]["details"]["date_mismatches"]
    assert len(mismatches) >= 1
    assert mismatches[0]["kind"] == "date"


def test_contradiction_no_conflict(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
    )
    con = r.signals["contradiction"]["value"]
    assert con < 0.2, f"no conflict expected, got {con}"


# ------------------------------------------------------------------
# COMPLETENESS
# ------------------------------------------------------------------
def test_completeness_fully_covered(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
    )
    com = r.signals["completeness"]["value"]
    assert com >= 0.9, f"fully covered expected, got {com}"


def test_completeness_partially_covered(evidence_engine):
    r = evidence_engine.evaluate(
        query="What is the refund period and does it apply to contractors?",
        answer="Customers can request refunds within 30 days.",
        evidence=["Customers may request refunds within 30 days."],
    )
    com = r.signals["completeness"]["value"]
    details = r.signals["completeness"]["details"]
    assert 0.2 <= com <= 0.8, f"partial coverage expected, got {com}"
    assert len(details["missing_aspects"]) >= 1


def test_completeness_missing_information(evidence_engine):
    r = evidence_engine.evaluate(
        query="What is the refund period and does it apply to contractors?",
        answer="Refunds within 30 days.",
        evidence=["The company was founded in 1999."],
    )
    com = r.signals["completeness"]["value"]
    assert com < 0.4, f"missing information expected, got {com}"


# ------------------------------------------------------------------
# EDGE CASES
# ------------------------------------------------------------------
def test_empty_evidence_conservative(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves.",
        evidence=[],
    )
    for name in ("relevance", "entailment", "contradiction", "completeness"):
        assert r.signals[name]["value"] <= 0.05, (
            f"{name} must be conservative with no evidence, "
            f"got {r.signals[name]['value']}"
        )


def test_duplicate_evidence_deduped(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=[
            "Employees are entitled to 18 casual leaves per year.",
            "Employees are entitled to 18 casual leaves per year.",
        ],
    )
    assert r.metadata["evidence_count"] == 1


def test_malformed_evidence_ignored(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=[None, 42, "", "Employees are entitled to 18 casual leaves per year."],
    )
    assert r.metadata["evidence_count"] == 1


def test_missing_metadata_does_not_crash(evidence_engine):
    # evidence_metadata omitted entirely
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
    )
    assert r.decision_ready is True


def test_empty_answer_conservative(evidence_engine):
    r = evidence_engine.evaluate(
        query="How many casual leaves?",
        answer="",
        evidence=["Employees are entitled to 18 casual leaves per year."],
    )
    ent = r.signals["entailment"]["value"]
    assert ent <= 0.05, f"empty answer must yield low support, got {ent}"
