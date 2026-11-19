"""Decision history API (/v1/decisions), backed by the SQLite audit log."""

import sqlite3

from fastapi.testclient import TestClient

from app.audit import AuditLogger
from app.core.evaluator import Evaluator
from app.escalation import EscalationQueue
from app.evidence.stubs import FixedSignal
from app.main import create_app

GOOD = dict(relevance=0.95, entailment=0.95, contradiction=0.02,
            freshness=0.9, completeness=0.9, ambiguity=0.04)

PAYLOAD = {
    "query": "How many casual leaves can an employee take?",
    "answer": "Employees can take 18 casual leaves.",
    "evidence": [{"text": "Employees are entitled to 18 casual leaves.",
                  "source": "policy_2026.pdf", "date": "2026-08-01", "version": "v3"}],
}


def make_client(**overrides):
    values = {**GOOD, **overrides}
    evaluator = Evaluator([FixedSignal(n, v) for n, v in values.items()])
    audit = AuditLogger(":memory:")
    app = create_app(evaluator, audit_logger=audit,
                     escalation_queue=EscalationQueue(":memory:"))
    return TestClient(app), audit


def test_history_lists_newest_first_with_counts():
    client, _ = make_client()
    ids = [client.post("/v1/evaluate", json=PAYLOAD).json()["request_id"] for _ in range(3)]
    body = client.get("/v1/decisions").json()
    assert body["total"] == 3
    assert body["counts"] == {"ANSWER": 3}
    assert [i["request_id"] for i in body["items"]] == list(reversed(ids))
    assert body["items"][0]["query"] == PAYLOAD["query"]
    assert "answer" not in body["items"][0]


def test_history_filters_by_decision():
    client, _ = make_client()
    client.post("/v1/evaluate", json=PAYLOAD)
    client.post("/v1/evaluate", json={**PAYLOAD, "evidence": []})  # ABSTAIN
    body = client.get("/v1/decisions?decision=ABSTAIN").json()
    assert [i["decision"] for i in body["items"]] == ["ABSTAIN"]
    assert client.get("/v1/decisions?decision=MAYBE").status_code == 422


def test_detail_returns_full_response_with_trace():
    client, _ = make_client()
    evaluated = client.post("/v1/evaluate", json=PAYLOAD).json()
    body = client.get(f"/v1/decisions/{evaluated['request_id']}").json()
    assert body["record"]["decision"] == "ANSWER"
    assert body["response"]["request_id"] == evaluated["request_id"]
    assert body["response"]["decision"] == evaluated["decision"]
    assert body["response"]["trace"]["request_id"] == evaluated["request_id"]


def test_detail_unknown_id_is_404():
    client, _ = make_client()
    assert client.get("/v1/decisions/nope").status_code == 404


def test_full_evidence_text_is_not_stored_in_response_json():
    client, audit = make_client()
    long_text = "Employees are entitled to 18 casual leaves. " + "x" * 500
    payload = {**PAYLOAD, "evidence": [{**PAYLOAD["evidence"][0], "text": long_text}]}
    rid = client.post("/v1/evaluate", json=payload).json()["request_id"]
    raw = audit._shared_conn.execute(
        "SELECT response_json FROM audit_logs WHERE request_id = ?", (rid,)
    ).fetchone()[0]
    assert long_text not in raw


def test_legacy_db_without_response_json_is_migrated(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE audit_logs (request_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, "
            "query TEXT, answer TEXT, profile TEXT, decision TEXT, answerability_score REAL, "
            "signals TEXT, reason_codes TEXT, generation_success INTEGER, "
            "error_message TEXT, latency_ms REAL)"
        )
        conn.execute("INSERT INTO audit_logs (request_id, timestamp, decision) "
                     "VALUES ('old', '2026-01-01T00:00:00+00:00', 'ANSWER')")
    audit = AuditLogger(db)
    record = audit.get_record("old")
    assert record["decision"] == "ANSWER"
    assert record["response"] is None
    assert audit.count_records() == {"ANSWER": 1}
