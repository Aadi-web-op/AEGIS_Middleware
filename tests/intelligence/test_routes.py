"""/v1/intelligence through the real app (create_app + TestClient)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.audit import AuditLogger
from app.main import create_app
from tests.intelligence.fakes import FakeReadDriver, down_driver, overview_row, seed_audit
from tests.intelligence.test_service import CIRC, LEAVE_V1, TRAVEL, scenario_rows

GRAPH_ONLY = [
    "/v1/intelligence/documents",
    "/v1/intelligence/contradictions",
    "/v1/intelligence/stale-usage",
    "/v1/intelligence/knowledge-gaps",
    f"/v1/intelligence/blast-radius?doc_id={TRAVEL}",
]

AUDIT_RECORDS = [
    {"request_id": "demo-1", "timestamp": "2026-04-01T10:00:00+00:00", "decision": "ESCALATE",
     "reason_codes": ["CONTRADICTION"], "query": "What is the meal allowance?"},
    {"request_id": "demo-2", "timestamp": "2026-04-01T12:00:00+00:00", "decision": "CAVEAT",
     "reason_codes": ["CONTRADICTION"], "query": "Meal allowance per day?"},
    {"request_id": "demo-4", "timestamp": "2026-04-02T09:00:00+00:00", "decision": "ABSTAIN",
     "reason_codes": ["LOW_EVIDENCE"], "query": "Equity vesting?"},
    {"request_id": "other-1", "timestamp": "2026-04-02T09:30:00+00:00", "decision": "ANSWER",
     "reason_codes": [], "query": "Hotel approval?"},
]


class _StubEvaluator:
    """create_app needs an evaluator; these tests never evaluate.
    A non-None graph_sink stops create_app from wiring a real writer."""
    graph_sink = object()


def _client(tmp_path, driver=None, records=AUDIT_RECORDS) -> TestClient:
    db = str(tmp_path / "audit.db")
    seed_audit(db, records)
    app = create_app(evaluator=_StubEvaluator(), neo4j_driver=driver,
                     audit_logger=AuditLogger(db))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Neo4j absent / down
# ---------------------------------------------------------------------------
def test_summary_without_neo4j_is_200_with_audit_parts(tmp_path):
    r = _client(tmp_path).get("/v1/intelligence/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["graph"]["available"] is False and body["graph"]["reason"]
    assert body["findings"] == []
    assert body["decision_distribution"] == {"ESCALATE": 1, "CAVEAT": 1, "ABSTAIN": 1, "ANSWER": 1}
    assert body["reason_distribution"] == {"CONTRADICTION": 2, "LOW_EVIDENCE": 1}
    data = body["data"]
    assert data["total_decisions"] == 4 and data["graph_decisions"] == 0
    assert data["sufficient"] is False and data["min_required"] == 5
    assert data["message"]
    for key in ("generated_at", "data", "decision_distribution", "reason_distribution",
                "findings", "graph"):
        assert key in body


@pytest.mark.parametrize("path", GRAPH_ONLY)
def test_graph_only_endpoints_503_without_driver(tmp_path, path):
    r = _client(tmp_path).get(path)
    assert r.status_code == 503
    assert r.json()["graph_available"] is False
    assert "not configured" in r.json()["detail"]


@pytest.mark.parametrize("path", GRAPH_ONLY)
def test_graph_only_endpoints_503_when_unreachable_without_leaking(tmp_path, path):
    r = _client(tmp_path, driver=down_driver()).get(path)
    assert r.status_code == 503
    body = r.json()
    assert body["graph_available"] is False
    assert "localhost:7687" not in body["detail"] and "Traceback" not in r.text


def test_summary_when_unreachable_is_200_and_audit_still_works(tmp_path):
    client = _client(tmp_path, driver=down_driver())
    r = client.get("/v1/intelligence/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["graph"]["available"] is False
    assert "localhost:7687" not in body["graph"]["reason"]
    assert sum(body["decision_distribution"].values()) == 4
    assert client.get("/v1/intelligence/trends").status_code == 200


def test_query_error_is_503_but_not_remembered_as_down(tmp_path):
    driver = FakeReadDriver(scenario_rows(), fail_on=lambda name: name == "conflict_edges")
    client = _client(tmp_path, driver=driver)
    assert client.get("/v1/intelligence/contradictions").status_code == 503
    # not a connectivity failure, so other endpoints still query the graph
    assert client.get("/v1/intelligence/knowledge-gaps").status_code == 200


class _CountingDownDriver(FakeReadDriver):
    """Unreachable server; counts how often a session is opened."""

    def __init__(self):
        super().__init__(session_error=down_driver().session_error)
        self.sessions = 0

    def session(self, **kw):
        self.sessions += 1
        return super().session(**kw)


def test_unreachable_is_remembered_so_polling_fails_fast(tmp_path):
    driver = _CountingDownDriver()
    client = _client(tmp_path, driver=driver)
    assert client.get("/v1/intelligence/summary").status_code == 200
    assert driver.sessions == 1  # summary stops at the first failing query
    assert client.get("/v1/intelligence/summary").json()["graph"]["available"] is False
    assert client.get("/v1/intelligence/stale-usage").status_code == 503
    assert driver.sessions == 1, "requests inside the down window did not hit the driver"


def test_down_marker_expires(tmp_path, monkeypatch):
    from app.intelligence import routes

    driver = _CountingDownDriver()
    client = _client(tmp_path, driver=driver)
    client.get("/v1/intelligence/documents")
    monkeypatch.setattr(routes, "DOWN_TTL_SECONDS", 0.0)
    client.app.state.graph_down_until = 0.0
    client.get("/v1/intelligence/documents")
    assert driver.sessions == 2


# ---------------------------------------------------------------------------
# With graph data
# ---------------------------------------------------------------------------
def test_summary_with_graph(tmp_path):
    client = _client(tmp_path, driver=FakeReadDriver(scenario_rows()))
    body = client.get("/v1/intelligence/summary", params={"request_prefix": "demo-"}).json()
    assert body["graph"] == {"available": True}
    assert body["data"]["sufficient"] is True and body["data"]["graph_decisions"] == 8
    # audit parts respect the prefix too
    assert body["decision_distribution"] == {"ESCALATE": 1, "CAVEAT": 1, "ABSTAIN": 1}
    assert body["findings"]
    for f in body["findings"]:
        assert set(f) >= {"id", "kind", "severity", "title", "explanation", "metric",
                          "subjects", "request_ids", "query"}
        assert set(f["metric"]) == {"name", "value", "numerator", "denominator"}
        assert f["severity"] in ("high", "medium", "low")
        assert len(f["request_ids"]) >= 2


def test_summary_insufficient(tmp_path):
    rows = {"graph_decision_count": [{"n": 2}],
            "decision_overview": [overview_row("a", "ABSTAIN"), overview_row("b", "ANSWER")]}
    body = _client(tmp_path, driver=FakeReadDriver(rows)).get("/v1/intelligence/summary").json()
    assert body["graph"]["available"] is True
    assert body["data"]["sufficient"] is False
    assert "3 more are needed" in body["data"]["message"]
    assert body["findings"] == []


def test_documents_contract_fields(tmp_path):
    body = _client(tmp_path, driver=FakeReadDriver(scenario_rows())).get(
        "/v1/intelligence/documents").json()
    assert body["items"]
    for item in body["items"]:
        assert set(item) >= {"doc_id", "source", "version", "decisions", "supported_claims",
                             "unsupported_or_contradicted_claims", "unsupported_rate",
                             "conflicts", "escalations", "abstains", "superseded_by"}
        assert not any(k.startswith("_") for k in item)
    by_id = {i["doc_id"]: i for i in body["items"]}
    assert by_id[LEAVE_V1]["superseded_by"] == ["doc:leave.pdf@v2"]
    assert by_id[TRAVEL]["conflicts"] == 3


def test_contradictions_stale_and_gaps(tmp_path):
    client = _client(tmp_path, driver=FakeReadDriver(scenario_rows()))
    (pair,) = client.get("/v1/intelligence/contradictions").json()["items"]
    assert {pair["doc_a"], pair["doc_b"]} == {CIRC, TRAVEL}
    assert pair["request_ids"] == ["demo-1", "demo-2", "demo-3"]
    assert pair["kinds"] == ["numeric"]

    stale = client.get("/v1/intelligence/stale-usage").json()
    (item,) = stale["items"]
    assert item["older_doc_id"] == LEAVE_V1 and item["request_ids"] == ["demo-6", "demo-7"]
    assert item["supersedes_basis"] == "graph_edge"

    gaps = client.get("/v1/intelligence/knowledge-gaps").json()
    assert gaps["min_decisions_per_topic"] == 2
    assert gaps["items"][0]["topic"] == "equity|vesting"
    assert gaps["items"][0]["request_ids"] == ["demo-4", "demo-5"]


def test_blast_radius(tmp_path):
    client = _client(tmp_path, driver=FakeReadDriver(scenario_rows()))
    assert client.get("/v1/intelligence/blast-radius").status_code == 422
    r = client.get("/v1/intelligence/blast-radius", params={"doc_id": "doc:nope"})
    assert r.status_code == 404
    body = client.get("/v1/intelligence/blast-radius", params={"doc_id": TRAVEL}).json()
    assert body["doc_id"] == TRAVEL
    assert body["relied_on"]["count"] == 0
    assert body["retrieved_only"]["count"] == 3


def test_trends(tmp_path):
    client = _client(tmp_path)
    day = client.get("/v1/intelligence/trends").json()
    assert day["bucket"] == "day"
    assert [(i["bucket"], i["total"]) for i in day["items"]] == [("2026-04-01", 2), ("2026-04-02", 2)]
    hour = client.get("/v1/intelligence/trends", params={"bucket": "hour"}).json()
    assert [i["bucket"] for i in hour["items"]] == ["2026-04-01T10", "2026-04-01T12", "2026-04-02T09"]
    scoped = client.get("/v1/intelligence/trends", params={"request_prefix": "other-"}).json()
    assert scoped["items"] == [{"bucket": "2026-04-02", "total": 1, "ANSWER": 1, "CAVEAT": 0,
                                "ESCALATE": 0, "ABSTAIN": 0}]
    assert client.get("/v1/intelligence/trends", params={"bucket": "week"}).status_code == 422


def test_trends_on_empty_audit_db(tmp_path):
    client = _client(tmp_path, records=[])
    assert client.get("/v1/intelligence/trends").json()["items"] == []
    body = client.get("/v1/intelligence/summary").json()
    assert body["data"]["total_decisions"] == 0
    assert body["decision_distribution"] == {}
