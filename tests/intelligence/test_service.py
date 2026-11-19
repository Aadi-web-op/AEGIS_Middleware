"""Rows -> tables/findings (pure functions) and IntelligenceService orchestration."""

from __future__ import annotations

import pytest

from app.intelligence import rules, service
from app.intelligence.audit import AuditReader
from app.intelligence.queries import QUERIES
from app.intelligence.service import (
    GraphUnavailable,
    IntelligenceService,
    build_contradiction_pairs,
    build_document_table,
    build_knowledge_gaps,
    build_stale_usage,
    contradiction_findings,
    escalation_root_cause_findings,
    knowledge_gap_findings,
    newer_older,
    sort_findings,
    split_blast_radius,
    stale_findings,
    sufficiency,
    supersession_map,
    uncertainty_source_findings,
    unsupported_source_findings,
)
from tests.intelligence.fakes import (
    FakeReadDriver,
    conflict_row,
    doc_row,
    down_driver,
    overview_row,
    seed_audit,
    usage_row,
)

LEAVE_V1 = "doc:leave.pdf@v1"
LEAVE_V2 = "doc:leave.pdf@v2"
TRAVEL = "doc:travel.pdf@v3"
CIRC = "doc:circular.pdf@v1"


# ---------------------------------------------------------------------------
# unsupported_source
# ---------------------------------------------------------------------------
def test_unsupported_source_direct_finding_from_contradicted_claims():
    overview = [overview_row("r1", "ESCALATE", claims=2, supported=0),
                overview_row("r2", "CAVEAT", claims=2, supported=1)]
    usage = [usage_row("r1", CIRC, decision="ESCALATE", contradicted_by_doc=1),
             usage_row("r2", CIRC, decision="CAVEAT", contradicted_by_doc=1)]
    table = build_document_table(overview, usage, [])
    findings = unsupported_source_findings(table)
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "unsupported_source" and f.attribution == "direct"
    assert f.metric.numerator == 2 and f.metric.denominator == 4 and f.metric.value == 0.5
    assert f.severity == "high"  # contradicted rate >= 0.5
    assert f.request_ids == ["r1", "r2"]
    assert f.query == "decision_document_usage"
    assert "2 of the 4 claims" in f.explanation


def test_unsupported_source_considered_is_capped_and_worded_as_cooccurrence():
    overview = [overview_row(r, "ABSTAIN", claims=1, supported=0) for r in ("r1", "r2", "r3")]
    usage = [usage_row(r, TRAVEL, decision="ABSTAIN") for r in ("r1", "r2", "r3")]
    findings = unsupported_source_findings(build_document_table(overview, usage, []))
    assert len(findings) == 1
    f = findings[0]
    assert f.attribution == "considered"
    assert f.severity == "medium"  # 100% over 3 decisions, capped at medium
    assert "co-occurrence" in f.explanation
    assert f.metric.name == "unsupported_claim_rate"
    assert (f.metric.numerator, f.metric.denominator) == (3, 3)


def test_unsupported_source_single_decision_is_not_a_finding():
    overview = [overview_row("r1", "ESCALATE", claims=3, supported=0)]
    usage = [usage_row("r1", CIRC, contradicted_by_doc=3)]
    assert unsupported_source_findings(build_document_table(overview, usage, [])) == []


def test_unsupported_source_below_rate_is_not_a_finding():
    overview = [overview_row("r1", "ANSWER", claims=4, supported=3),
                overview_row("r2", "ANSWER", claims=4, supported=3)]
    usage = [usage_row("r1", TRAVEL), usage_row("r2", TRAVEL)]
    assert unsupported_source_findings(build_document_table(overview, usage, [])) == []


def test_document_table_contract_fields_and_counts():
    overview = [overview_row("r1", "ESCALATE", claims=2, supported=1),
                overview_row("r2", "ABSTAIN", claims=0)]
    usage = [usage_row("r1", LEAVE_V1, decision="ESCALATE", supported_by_doc=1),
             usage_row("r1", LEAVE_V1, decision="ESCALATE", supported_by_doc=1),  # duplicate
             usage_row("r2", LEAVE_V1, decision="ABSTAIN")]
    conflicts = [conflict_row("r1", LEAVE_V1, LEAVE_V2)]
    table = build_document_table(overview, usage, conflicts, {LEAVE_V1: {LEAVE_V2: "graph_edge"}})
    (row,) = table
    for key in ("doc_id", "source", "version", "decisions", "supported_claims",
                "unsupported_or_contradicted_claims", "unsupported_rate", "conflicts",
                "escalations", "abstains", "superseded_by"):
        assert key in row
    assert row["decisions"] == 2
    assert row["supported_claims"] == 1
    assert row["unsupported_or_contradicted_claims"] == 1
    assert row["unsupported_rate"] == 0.5
    assert (row["conflicts"], row["escalations"], row["abstains"]) == (1, 1, 1)
    assert row["superseded_by"] == [LEAVE_V2]


def test_rows_without_ids_are_skipped_not_guessed():
    overview = [overview_row("r1", "ABSTAIN"), {"request_id": None, "decision": "ABSTAIN"}]
    usage = [usage_row("r1", TRAVEL), {**usage_row("r2", TRAVEL), "doc_id": None}]
    table = build_document_table(overview, usage, [])
    assert [r["doc_id"] for r in table] == [TRAVEL]
    assert table[0]["decisions"] == 1
    assert uncertainty_source_findings(overview) == []


# ---------------------------------------------------------------------------
# contradiction_hotspot
# ---------------------------------------------------------------------------
def test_contradiction_pair_is_canonical_and_counts_distinct_decisions():
    conflicts = [conflict_row("r1", TRAVEL, CIRC, value_a="75", value_b="50"),
                 conflict_row("r2", CIRC, TRAVEL, decision="CAVEAT", value_a="50", value_b="75")]
    usage = [usage_row(r, d) for r in ("r1", "r2", "r3") for d in (TRAVEL, CIRC)]
    (pair,) = build_contradiction_pairs(conflicts, usage)
    assert (pair["doc_a"], pair["doc_b"]) == (CIRC, TRAVEL)
    assert pair["decision_count"] == 2
    assert pair["decisions_retrieving_both"] == 3
    assert pair["request_ids"] == ["r1", "r2"]
    # values are re-oriented to the canonical (doc_a, doc_b) order
    assert all((s["value_a"], s["value_b"]) == ("50", "75") for s in pair["sample_values"])

    (f,) = contradiction_findings([pair])
    assert f.kind == "contradiction_hotspot"
    assert f.severity == "high"  # numeric conflict and one answer was still shown
    assert (f.metric.numerator, f.metric.denominator) == (2, 3)
    assert f.query == "conflict_edges"
    assert "2 of the 3 decisions" in f.explanation
    assert {s.id for s in f.subjects} == {CIRC, TRAVEL}


def test_contradiction_in_one_decision_is_not_a_finding():
    pairs = build_contradiction_pairs([conflict_row("r1", TRAVEL, CIRC),
                                       conflict_row("r1", TRAVEL, CIRC, kind="date")], [])
    assert pairs[0]["decision_count"] == 1
    assert contradiction_findings(pairs) == []


# ---------------------------------------------------------------------------
# stale_version_in_use
# ---------------------------------------------------------------------------
def test_newer_older_by_date_then_version():
    a, b = doc_row(LEAVE_V1, "leave.pdf", "v1", "2025-01-10"), doc_row(LEAVE_V2, "leave.pdf", "v2", "2026-03-01")
    assert newer_older(a, b) == (b, a)
    a2, b2 = doc_row(LEAVE_V1, "leave.pdf", "v1"), doc_row(LEAVE_V2, "leave.pdf", "v2")
    assert newer_older(a2, b2) == (b2, a2)
    # incomparable version labels -> no order
    assert newer_older(doc_row("doc:x@1.2", "x", "1.2"), doc_row("doc:x@3", "x", "3")) is None


def test_supersession_map_derives_without_edges_and_keeps_graph_edges():
    docs = [doc_row(LEAVE_V1, "leave.pdf", "v1"), doc_row(LEAVE_V2, "leave.pdf", "v2"),
            doc_row(TRAVEL, "travel.pdf", "v3")]
    derived = supersession_map(docs, [])
    assert derived == {LEAVE_V1: {LEAVE_V2: "derived_from_version_or_date"}}
    edged = supersession_map(docs, [{"newer": LEAVE_V2, "older": LEAVE_V1}])
    assert edged[LEAVE_V1][LEAVE_V2] == "graph_edge"


def _stale_fixture():
    documents = [doc_row(LEAVE_V1, "leave.pdf", "v1", "2025-01-10"),
                 doc_row(LEAVE_V2, "leave.pdf", "v2", "2026-03-01")]
    usage = [
        usage_row("r1", LEAVE_V1, decision="ANSWER", created_at="2026-04-01T10:00:00+00:00", supported_by_doc=1),
        usage_row("r2", LEAVE_V1, decision="ESCALATE", created_at="2026-05-01T10:00:00+00:00"),
        usage_row("r3", LEAVE_V1, decision="ANSWER", created_at="2025-06-01T10:00:00+00:00"),  # before v2
        usage_row("r4", LEAVE_V1, decision="ANSWER"),  # no created_at
        usage_row("r5", LEAVE_V2, decision="ANSWER", created_at="2026-04-02T10:00:00+00:00"),
    ]
    return usage, documents


def test_stale_usage_counts_only_dated_decisions_after_cutoff():
    usage, documents = _stale_fixture()
    items, exclusions = build_stale_usage(usage, documents, [])
    (item,) = items
    assert item["older_doc_id"] == LEAVE_V1 and item["newer_doc_id"] == LEAVE_V2
    assert item["cutoff"] == "2026-03-01" and item["cutoff_basis"] == "newer_document_date"
    assert item["supersedes_basis"] == "derived_from_version_or_date"
    assert item["request_ids"] == ["r1", "r2"]
    assert item["relied_request_ids"] == ["r1"]
    assert item["eligible_decisions"] == 3  # r1, r2 + r5 on the newer version
    assert [e.count for e in exclusions] == [1]  # r4: no created_at
    assert exclusions[0].rule == "stale_version_in_use"

    (f,) = stale_findings(items)
    assert f.severity == "high"  # r1 showed an answer supported by v1
    assert (f.metric.numerator, f.metric.denominator) == (2, 3)
    assert f.query == "decision_document_usage+supersedes_edges"
    assert all(part in QUERIES for part in f.query.split("+"))


def test_stale_cutoff_falls_back_to_first_retrieval_of_newer():
    documents = [doc_row(LEAVE_V1, "leave.pdf", "v1"), doc_row(LEAVE_V2, "leave.pdf", "v2")]
    usage = [usage_row("r5", LEAVE_V2, created_at="2026-04-02T00:00:00+00:00"),
             usage_row("r1", LEAVE_V1, created_at="2026-04-01T00:00:00+00:00"),
             usage_row("r2", LEAVE_V1, created_at="2026-04-03T00:00:00+00:00"),
             usage_row("r3", LEAVE_V1, created_at="2026-04-04T00:00:00+00:00")]
    (item,), _ = build_stale_usage(usage, documents, [])
    assert item["cutoff_basis"] == "first_retrieval_of_newer"
    assert item["request_ids"] == ["r2", "r3"]
    (f,) = stale_findings([item])
    assert f.severity == "medium"


def test_stale_without_any_cutoff_is_excluded():
    documents = [doc_row(LEAVE_V1, "leave.pdf", "v1"), doc_row(LEAVE_V2, "leave.pdf", "v2")]
    usage = [usage_row("r1", LEAVE_V1, created_at="2026-04-01"),
             usage_row("r2", LEAVE_V1, created_at="2026-04-02")]
    items, exclusions = build_stale_usage(usage, documents, [])
    assert items == []
    assert exclusions and "no cutoff" in exclusions[0].reason


def test_single_stale_decision_is_not_a_finding():
    usage, documents = _stale_fixture()
    usage = [u for u in usage if u["request_id"] != "r2"]
    items, _ = build_stale_usage(usage, documents, [])
    assert items[0]["stale_decisions"] == 1
    assert stale_findings(items) == []


# ---------------------------------------------------------------------------
# knowledge_gap
# ---------------------------------------------------------------------------
def test_knowledge_gap_by_stored_topic():
    overview = [overview_row("r1", "ABSTAIN", topic="equity|vesting", query_preview="When does equity vest?"),
                overview_row("r2", "ABSTAIN", topic="equity|vesting"),
                overview_row("r3", "ESCALATE", topic="equity|vesting"),
                overview_row("r4", "ANSWER", topic="leave|annual"),  # single-decision topic: dropped
                ]
    items, exclusions = build_knowledge_gaps(overview)
    assert [i["topic"] for i in items] == ["equity|vesting"]
    assert exclusions == []
    item = items[0]
    assert (item["abstains"], item["escalations"], item["gap_rate"]) == (2, 1, 1.0)
    assert item["sample_queries"] == ["When does equity vest?"]
    (f,) = knowledge_gap_findings(items)
    assert f.severity == "high" and f.query == "decision_overview"
    assert f.request_ids == ["r1", "r2", "r3"]
    assert "3 of 3 decisions" in f.explanation


def test_knowledge_gap_topic_falls_back_to_audit_query_then_excludes():
    overview = [overview_row("r1", "ABSTAIN"), overview_row("r2", "ANSWER"),
                overview_row("r3", "ABSTAIN")]  # r3 has no topic and no audit query
    audit_queries = {"r1": "Equity vesting schedule?", "r2": "equity vesting cliff?"}
    items, exclusions = build_knowledge_gaps(audit_queries=audit_queries, overview=overview,
                                             topic_fn=lambda q: "equity|vesting")
    (item,) = items
    assert item["topic_sources"] == ["audit_query"]
    assert item["decisions"] == 2 and item["gap_rate"] == 0.5
    assert exclusions[0].count == 1
    (f,) = knowledge_gap_findings(items) or [None]
    # 1 gap decision < 2 -> not a finding
    assert f is None


def test_knowledge_gap_below_rate_is_not_a_finding():
    overview = [overview_row(f"r{i}", "ANSWER", topic="t") for i in range(4)] + [
        overview_row("g1", "ABSTAIN", topic="t"), overview_row("g2", "ABSTAIN", topic="t")]
    items, _ = build_knowledge_gaps(overview)
    assert items[0]["gap_rate"] == 0.3333
    assert knowledge_gap_findings(items) == []


# ---------------------------------------------------------------------------
# escalation_root_cause / uncertainty_source
# ---------------------------------------------------------------------------
def test_escalation_root_cause():
    rows = [{"request_id": "r1", "code": "CONTRADICTION", "doc_id": CIRC},
            {"request_id": "r2", "code": "CONTRADICTION", "doc_id": CIRC},
            {"request_id": "r2", "code": "CONTRADICTION", "doc_id": TRAVEL}]
    overview = [overview_row(r, "ESCALATE") for r in ("r1", "r2", "r3", "r4")]
    findings = escalation_root_cause_findings(rows, overview)
    assert len(findings) == 1  # TRAVEL appears in one escalation only
    f = findings[0]
    assert f.subjects[0].id == CIRC
    assert (f.metric.numerator, f.metric.denominator, f.metric.value) == (2, 4, 0.5)
    assert f.severity == "high"
    assert f.query == "escalation_root_causes"
    assert f.details["reason_codes"] == {"CONTRADICTION": 2}


def test_uncertainty_source():
    overview = [overview_row("r1", "ABSTAIN", reason_codes=["LOW_EVIDENCE"]),
                overview_row("r2", "ESCALATE", reason_codes=["LOW_EVIDENCE", "CONTRADICTION"]),
                overview_row("r3", "ABSTAIN", reason_codes=[]),
                overview_row("r4", "ABSTAIN", reason_codes=[]),
                overview_row("r5", "ABSTAIN", reason_codes=[]),
                overview_row("r6", "ANSWER", reason_codes=["LOW_EVIDENCE"])]  # not a gap decision
    findings = uncertainty_source_findings(overview)
    assert [f.subjects[0].id for f in findings] == ["LOW_EVIDENCE"]  # CONTRADICTION: 1 decision
    f = findings[0]
    assert (f.metric.numerator, f.metric.denominator) == (2, 5)
    assert f.severity == "medium"
    assert f.request_ids == ["r1", "r2"]


# ---------------------------------------------------------------------------
# cross-cutting
# ---------------------------------------------------------------------------
def test_request_ids_are_sorted_deduplicated_and_capped():
    ids = [f"r{i:02d}" for i in range(25)]
    overview = [overview_row(r, "ABSTAIN", topic="t") for r in reversed(ids)]
    items, _ = build_knowledge_gaps(overview)
    (f,) = knowledge_gap_findings(items)
    assert f.request_ids == sorted(ids)[: rules.MAX_REQUEST_IDS]
    assert f.metric.numerator == 25  # the metric still counts everything


def test_finding_ids_are_stable_across_runs():
    overview = [overview_row(r, "ABSTAIN", topic="t") for r in ("a", "b")]
    first = knowledge_gap_findings(build_knowledge_gaps(overview)[0])[0].id
    second = knowledge_gap_findings(build_knowledge_gaps(list(reversed(overview)))[0])[0].id
    assert first == second


def test_sort_findings_severity_then_numerator():
    overview = [overview_row(f"a{i}", "ABSTAIN", topic="big") for i in range(5)] + [
        overview_row(f"b{i}", "ABSTAIN", topic="small") for i in range(2)]
    found = sort_findings(knowledge_gap_findings(build_knowledge_gaps(overview)[0]))
    assert [f.subjects[0].id for f in found] == ["big", "small"]  # high before medium


@pytest.mark.parametrize("n,needed,sufficient", [(0, 5, False), (4, 1, False), (5, 0, True), (9, 0, True)])
def test_sufficiency_message(n, needed, sufficient):
    data = sufficiency(n, total_decisions=12, graph_available=True)
    assert data["sufficient"] is sufficient
    assert data["needed"] == needed
    assert data["min_required"] == 5
    if needed:
        assert f"{needed} more" in data["message"]


def test_sufficiency_when_graph_unavailable():
    data = sufficiency(0, 3, graph_available=False)
    assert data["sufficient"] is False
    assert "unavailable" in data["message"]


def test_split_blast_radius():
    usage = [usage_row("r1", CIRC, supported_by_doc=2, decision="ANSWER", texts=["Meals: $50"]),
             usage_row("r2", CIRC, decision="ESCALATE"),
             usage_row("r2", CIRC, decision="ESCALATE"),
             usage_row("r3", TRAVEL)]
    result = split_blast_radius(CIRC, usage)
    assert result["total_decisions"] == 2
    assert result["relied_on"]["count"] == 1
    assert result["relied_on"]["decisions"][0]["claims"] == ["Meals: $50"]
    assert [d["request_id"] for d in result["retrieved_only"]["decisions"]] == ["r2"]


# ---------------------------------------------------------------------------
# IntelligenceService with a fake driver
# ---------------------------------------------------------------------------
def scenario_rows():
    """Eight decisions on a small fictional corpus."""
    overview = [
        overview_row("demo-1", "ESCALATE", claims=1, reason_codes=["CONTRADICTION"], topic="meal|allowance"),
        overview_row("demo-2", "CAVEAT", claims=1, reason_codes=["CONTRADICTION"], topic="meal|allowance"),
        overview_row("demo-3", "ESCALATE", claims=1, reason_codes=["CONTRADICTION"], topic="meal|allowance"),
        overview_row("demo-4", "ABSTAIN", claims=0, reason_codes=["LOW_EVIDENCE"], topic="equity|vesting"),
        overview_row("demo-5", "ABSTAIN", claims=0, reason_codes=["LOW_EVIDENCE"], topic="equity|vesting"),
        overview_row("demo-6", "ANSWER", claims=1, supported=1, topic="leave|annual",
                     created_at="2026-04-01T00:00:00+00:00"),
        overview_row("demo-7", "ANSWER", claims=1, supported=1, topic="leave|annual",
                     created_at="2026-04-02T00:00:00+00:00"),
        overview_row("demo-8", "ANSWER", claims=1, supported=1, topic="leave|annual",
                     created_at="2026-04-03T00:00:00+00:00"),
    ]
    usage = []
    for rid, dec in (("demo-1", "ESCALATE"), ("demo-2", "CAVEAT"), ("demo-3", "ESCALATE")):
        usage += [usage_row(rid, TRAVEL, decision=dec, contradicted_by_doc=1),
                  usage_row(rid, CIRC, decision=dec)]
    for rid in ("demo-6", "demo-7"):
        usage.append(usage_row(rid, LEAVE_V1, source="leave.pdf", version="v1", date="2025-01-10",
                               created_at=f"2026-04-0{rid[-1] == '7' and 2 or 1}T00:00:00+00:00",
                               supported_by_doc=1))
    usage.append(usage_row("demo-8", LEAVE_V2, source="leave.pdf", version="v2", date="2026-03-01",
                           created_at="2026-04-03T00:00:00+00:00", supported_by_doc=1))
    conflicts = [conflict_row(r, TRAVEL, CIRC, decision=d, value_a="75", value_b="50")
                 for r, d in (("demo-1", "ESCALATE"), ("demo-2", "CAVEAT"), ("demo-3", "ESCALATE"))]
    documents = [doc_row(LEAVE_V1, "leave.pdf", "v1", "2025-01-10"),
                 doc_row(LEAVE_V2, "leave.pdf", "v2", "2026-03-01"),
                 doc_row(TRAVEL, "travel.pdf", "v3"), doc_row(CIRC, "circular.pdf", "v1")]
    root = [{"request_id": r, "code": "CONTRADICTION", "doc_id": TRAVEL, "source": "travel.pdf",
             "version": "v3", "paths": ["reason_about_evidence"]} for r in ("demo-1", "demo-3")]
    return {
        "graph_decision_count": [{"n": len(overview)}],
        "decision_overview": overview,
        "decision_document_usage": lambda p: [u for u in usage if p.get("doc_id") in (None, u["doc_id"])],
        "conflict_edges": conflicts,
        "documents": documents,
        "document_by_id": lambda p: [d for d in documents if d["doc_id"] == p.get("doc_id")],
        "supersedes_edges": [{"newer": LEAVE_V2, "older": LEAVE_V1}],
        "escalation_root_causes": root,
    }


def _svc(driver, tmp_path, records=()):
    db = str(tmp_path / "audit.db")
    seed_audit(db, records)
    return IntelligenceService(driver=driver, audit=AuditReader(db_path=db),
                               topic_fn=lambda q: "x")


def test_summary_every_finding_is_traceable(tmp_path):
    rows = scenario_rows()
    driver = FakeReadDriver(rows)
    out = _svc(driver, tmp_path).summary("demo-")
    assert out["graph"] == {"available": True}
    assert out["data"]["graph_decisions"] == 8 and out["data"]["sufficient"] is True
    stored_ids = {r["request_id"] for r in rows["decision_overview"]}
    kinds = {f["kind"] for f in out["findings"]}
    assert kinds == {"unsupported_source", "contradiction_hotspot", "stale_version_in_use",
                     "knowledge_gap", "escalation_root_cause", "uncertainty_source"}
    for f in out["findings"]:
        assert f["request_ids"], f
        assert len(set(f["request_ids"])) >= rules.MIN_DECISIONS_FOR_FINDING
        assert set(f["request_ids"]) <= stored_ids
        assert all(part in QUERIES for part in f["query"].split("+"))
        m = f["metric"]
        assert 0 < m["numerator"] <= m["denominator"]
        assert m["value"] == rules.rate(m["numerator"], m["denominator"])
        assert str(m["numerator"]) in f["explanation"]
    # every decision-scoped query got the prefix as a parameter (Documents
    # and SUPERSEDES are global facts, not owned by a decision)
    global_queries = {"documents", "supersedes_edges", "document_by_id"}
    for name, params in driver.calls:
        assert params["prefix"] == ("" if name in global_queries else "demo-")
        assert isinstance(params["limit"], int)


def test_summary_insufficient_data_still_reports(tmp_path):
    rows = scenario_rows()
    rows["graph_decision_count"] = [{"n": 3}]
    out = _svc(FakeReadDriver(rows), tmp_path).summary()
    assert out["data"]["sufficient"] is False
    assert out["data"]["needed"] == 2
    assert "2 more are needed" in out["data"]["message"]


def test_summary_degrades_when_graph_down_but_keeps_audit(tmp_path):
    records = [
        {"request_id": "a1", "timestamp": "2026-04-01T10:00:00+00:00", "decision": "ANSWER", "reason_codes": []},
        {"request_id": "a2", "timestamp": "2026-04-01T11:00:00+00:00", "decision": "ESCALATE",
         "reason_codes": ["CONTRADICTION", "CONTRADICTION"]},
    ]
    out = _svc(down_driver(), tmp_path, records).summary()
    assert out["graph"]["available"] is False and "reason" in out["graph"]
    assert out["findings"] == []
    assert out["decision_distribution"] == {"ANSWER": 1, "ESCALATE": 1}
    assert out["reason_distribution"] == {"CONTRADICTION": 1}  # once per decision
    assert out["data"]["total_decisions"] == 2 and out["data"]["sufficient"] is False


def test_summary_without_driver(tmp_path):
    out = _svc(None, tmp_path).summary()
    assert out["graph"]["available"] is False
    assert "not configured" in out["graph"]["reason"]


def test_summary_failure_midway_degrades(tmp_path):
    driver = FakeReadDriver(scenario_rows(), fail_on=lambda name: name == "conflict_edges")
    out = _svc(driver, tmp_path).summary()
    assert out["graph"]["available"] is False
    assert out["findings"] == []


def test_summary_survives_malformed_rows(tmp_path):
    rows = scenario_rows()
    rows["decision_overview"] = [overview_row("x", "ABSTAIN", claims="many")]
    rows["decision_document_usage"] = [usage_row("x", TRAVEL)]
    out = _svc(FakeReadDriver(rows), tmp_path).summary()
    assert out["graph"]["available"] is True
    assert "analysis_error" in out["graph"]
    assert out["findings"] == []


def test_summary_audit_unreadable(tmp_path):
    svc = IntelligenceService(driver=FakeReadDriver(scenario_rows()),
                              audit=AuditReader(db_path=str(tmp_path)))  # a directory
    out = svc.summary()
    assert out["audit"]["available"] is False
    assert out["graph"]["available"] is True and out["findings"]


def test_graph_only_methods_raise_graph_unavailable(tmp_path):
    svc = _svc(down_driver(), tmp_path)
    for call in (svc.documents, svc.contradictions, svc.stale_usage, svc.knowledge_gaps,
                 lambda: svc.blast_radius(TRAVEL)):
        with pytest.raises(GraphUnavailable):
            call()


def test_blast_radius_service(tmp_path):
    svc = _svc(FakeReadDriver(scenario_rows()), tmp_path)
    assert svc.blast_radius("doc:missing") is None
    result = svc.blast_radius(LEAVE_V1)
    assert result["document"]["doc_id"] == LEAVE_V1
    assert result["relied_on"]["count"] == 2
    assert [d["request_id"] for d in result["relied_on"]["decisions"]] == ["demo-6", "demo-7"]


def test_knowledge_gaps_uses_audit_query_fallback(tmp_path):
    rows = {"decision_overview": [overview_row("o1", "ABSTAIN"), overview_row("o2", "ESCALATE")]}
    records = [{"request_id": "o1", "timestamp": "2026-01-01T00:00:00+00:00", "decision": "ABSTAIN",
                "query": "How does equity vesting work?"},
               {"request_id": "o2", "timestamp": "2026-01-01T00:00:00+00:00", "decision": "ESCALATE",
                "query": "Equity vesting: how does it work?"}]
    db = str(tmp_path / "audit.db")
    seed_audit(db, records)
    svc = IntelligenceService(driver=FakeReadDriver(rows), audit=AuditReader(db_path=db))
    out = svc.knowledge_gaps()
    assert svc.topic_fn is not None  # app.graph.topics.topic_key
    (item,) = out["items"]
    assert item["topic_sources"] == ["audit_query"]
    assert item["topic"] == service.default_topic_fn()("How does equity vesting work?")
    assert item["gap_rate"] == 1.0


def test_trends_from_audit(tmp_path):
    records = [
        {"request_id": "t1", "timestamp": "2026-04-01T10:05:00+00:00", "decision": "ANSWER"},
        {"request_id": "t2", "timestamp": "2026-04-01T10:55:00+00:00", "decision": "ABSTAIN"},
        {"request_id": "t3", "timestamp": "2026-04-01T11:00:00+00:00", "decision": "ANSWER"},
        {"request_id": "x_1", "timestamp": "2026-04-02T09:00:00+00:00", "decision": "ESCALATE"},
    ]
    svc = _svc(None, tmp_path, records)
    days = svc.trends("day")["items"]
    assert [(d["bucket"], d["total"]) for d in days] == [("2026-04-01", 3), ("2026-04-02", 1)]
    assert days[0]["ANSWER"] == 2 and days[0]["ABSTAIN"] == 1
    hours = svc.trends("hour")["items"]
    assert [h["bucket"] for h in hours] == ["2026-04-01T10", "2026-04-01T11", "2026-04-02T09"]
    # prefix "t" scopes; "_" in a prefix is literal, not a LIKE wildcard
    assert sum(d["total"] for d in svc.trends("day", "t")["items"]) == 3
    assert sum(d["total"] for d in svc.trends("day", "x_")["items"]) == 1
    assert svc.trends("day", "t_")["items"] == []
