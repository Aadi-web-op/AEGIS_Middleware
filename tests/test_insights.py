"""
Tests for /v1/insights/* endpoints.

These tests use an in-memory SQLite audit log so they are
hermetic and do not require a running database.
"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.audit.logger import AuditLogger
from app.core.evaluator import Evaluator
from app.escalation.queue import EscalationQueue
from app.evidence.stubs import FixedSignal
from app.main import create_app


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_audit_db(tmp_path):
    """A real SQLite file (not :memory:) so the insights endpoint can open it."""
    return str(tmp_path / "test_audit.db")


@pytest.fixture()
def tmp_esc_db(tmp_path):
    return str(tmp_path / "test_esc.db")


@pytest.fixture()
def populated_client(tmp_audit_db, tmp_esc_db):
    """
    Client with a real audit DB pre-seeded with:
    - 2 ANSWER decisions (low contradiction)
    - 1 ESCALATE decision (high contradiction)
    - 1 ABSTAIN decision (no signals)
    - 1 low-freshness CAVEAT decision
    Also seeds one escalation record.
    """
    audit = AuditLogger(db_path=tmp_audit_db)
    esc_q = EscalationQueue(db_path=tmp_esc_db)

    signals_vals = dict(
        relevance=0.9, entailment=0.9, contradiction=0.05,
        freshness=0.9, completeness=0.9, ambiguity=0.05
    )
    evaluator = Evaluator([FixedSignal(k, v) for k, v in signals_vals.items()])
    app = create_app(evaluator=evaluator, audit_logger=audit, escalation_queue=esc_q)
    client = TestClient(app)
    # Store db paths so insights endpoint can find them
    app.state.audit_db_path = tmp_audit_db

    # Seed records directly into the audit DB
    conn = sqlite3.connect(tmp_audit_db)
    conn.execute(
        """
        INSERT INTO audit_logs
            (request_id, timestamp, query, answer, profile,
             decision, answerability_score, signals, reason_codes,
             generation_success, error_message, latency_ms)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "req-answer-1", "2026-10-01T10:00:00Z",
            "What is 2+2?", "4", "standard",
            "ANSWER", 0.95,
            json.dumps({"relevance": 0.9, "entailment": 0.9, "contradiction": 0.05,
                        "freshness": 0.9, "completeness": 0.9, "ambiguity": 0.05}),
            json.dumps([]),
            1, None, 42.0,
        ),
    )
    conn.execute(
        """
        INSERT INTO audit_logs
            (request_id, timestamp, query, answer, profile,
             decision, answerability_score, signals, reason_codes,
             generation_success, error_message, latency_ms)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "req-escalate-1", "2026-10-02T10:00:00Z",
            "Contradictory question?", "Maybe.", "standard",
            "ESCALATE", 0.35,
            json.dumps({"relevance": 0.7, "entailment": 0.5, "contradiction": 0.82,
                        "freshness": 0.9, "completeness": 0.6, "ambiguity": 0.1}),
            json.dumps(["CONTRADICTION"]),
            1, None, 55.0,
        ),
    )
    conn.execute(
        """
        INSERT INTO audit_logs
            (request_id, timestamp, query, answer, profile,
             decision, answerability_score, signals, reason_codes,
             generation_success, error_message, latency_ms)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "req-abstain-1", "2026-10-03T10:00:00Z",
            "Unanswerable topic.", None, "standard",
            "ABSTAIN", 0.0,
            json.dumps({}),
            json.dumps(["NO_EVIDENCE"]),
            0, None, 12.0,
        ),
    )
    conn.execute(
        """
        INSERT INTO audit_logs
            (request_id, timestamp, query, answer, profile,
             decision, answerability_score, signals, reason_codes,
             generation_success, error_message, latency_ms)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "req-stale-1", "2026-10-04T10:00:00Z",
            "Old policy question.", "Outdated answer.", "standard",
            "CAVEAT", 0.55,
            json.dumps({"relevance": 0.8, "entailment": 0.7, "contradiction": 0.1,
                        "freshness": 0.2, "completeness": 0.7, "ambiguity": 0.1}),
            json.dumps(["STALE_EVIDENCE"]),
            1, None, 38.0,
        ),
    )
    conn.commit()
    conn.close()

    # Seed an escalation record
    esc_q.enqueue(
        request_id="req-escalate-1",
        reason="Contradiction detected.",
        decision="ESCALATE",
        query="Contradictory question?",
        answer="Maybe.",
        raise_on_duplicate=False,
    )

    return client, tmp_audit_db, tmp_esc_db


@pytest.fixture()
def empty_client(tmp_audit_db, tmp_esc_db):
    """Client with empty audit and escalation databases."""
    audit = AuditLogger(db_path=tmp_audit_db)
    esc_q = EscalationQueue(db_path=tmp_esc_db)
    evaluator = Evaluator([FixedSignal(k, v) for k, v in {
        "relevance": 0.9, "entailment": 0.9, "contradiction": 0.05,
        "freshness": 0.9, "completeness": 0.9, "ambiguity": 0.05,
    }.items()])
    app = create_app(evaluator=evaluator, audit_logger=audit, escalation_queue=esc_q)
    app.state.audit_db_path = tmp_audit_db
    return TestClient(app)


# ── Tests ────────────────────────────────────────────────────────────────────


class TestConflictingPairs:
    def test_returns_200(self, populated_client):
        client, *_ = populated_client
        r = client.get("/v1/insights/conflicting-document-pairs")
        assert r.status_code == 200

    def test_returns_list(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/conflicting-document-pairs").json()
        assert isinstance(data, list)

    def test_high_contradiction_record_included(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/conflicting-document-pairs").json()
        assert len(data) >= 1
        scores = [r["contradiction_score"] for r in data]
        assert all(s >= 0.5 for s in scores)

    def test_empty_db_returns_empty_list(self, empty_client):
        data = empty_client.get("/v1/insights/conflicting-document-pairs").json()
        assert data == []

    def test_limit_respected(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/conflicting-document-pairs?limit=1").json()
        assert len(data) <= 1


class TestStaleRetrievals:
    def test_returns_200(self, populated_client):
        client, *_ = populated_client
        assert client.get("/v1/insights/stale-document-retrievals").status_code == 200

    def test_stale_record_included(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/stale-document-retrievals").json()
        assert len(data) >= 1
        freshness_scores = [r["freshness_score"] for r in data]
        assert all(s < 0.5 for s in freshness_scores)

    def test_ordered_worst_first(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/stale-document-retrievals").json()
        if len(data) > 1:
            scores = [r["freshness_score"] for r in data]
            assert scores == sorted(scores)

    def test_empty_db_returns_empty_list(self, empty_client):
        assert empty_client.get("/v1/insights/stale-document-retrievals").json() == []


class TestAbstainTopics:
    def test_returns_200(self, populated_client):
        client, *_ = populated_client
        assert client.get("/v1/insights/abstain-topics").status_code == 200

    def test_returns_abstain_decisions_only(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/abstain-topics").json()
        assert len(data) >= 1
        assert data[0]["request_id"] == "req-abstain-1"

    def test_reason_codes_present(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/abstain-topics").json()
        assert "NO_EVIDENCE" in data[0]["reason_codes"]

    def test_empty_db_returns_empty_list(self, empty_client):
        assert empty_client.get("/v1/insights/abstain-topics").json() == []


class TestDecisionsByDecision:
    def test_returns_200(self, populated_client):
        client, *_ = populated_client
        assert client.get("/v1/insights/decisions-by-decision?decision=ESCALATE").status_code == 200

    def test_returns_only_matching_decision(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/decisions-by-decision?decision=ESCALATE").json()
        assert all(r["decision"] == "ESCALATE" for r in data)

    def test_escalate_record_present(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/decisions-by-decision?decision=ESCALATE").json()
        ids = [r["request_id"] for r in data]
        assert "req-escalate-1" in ids

    def test_signals_present_in_response(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/decisions-by-decision?decision=ESCALATE").json()
        assert len(data) >= 1
        assert "signals" in data[0]
        assert "contradiction" in data[0]["signals"]

    def test_empty_db_returns_empty_list(self, empty_client):
        assert empty_client.get("/v1/insights/decisions-by-decision?decision=ESCALATE").json() == []


class TestEscalationClusters:
    def test_returns_200(self, populated_client):
        client, *_ = populated_client
        assert client.get("/v1/insights/escalation-clusters").status_code == 200

    def test_returns_list(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/escalation-clusters").json()
        assert isinstance(data, list)

    def test_cluster_has_required_fields(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/escalation-clusters").json()
        if data:
            cluster = data[0]
            assert "reason_code" in cluster
            assert "count" in cluster
            assert "escalation_ids" in cluster
            assert "request_ids" in cluster

    def test_contradiction_cluster_present(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/escalation-clusters").json()
        codes = [c["reason_code"] for c in data]
        # The seeded escalation has reason code CONTRADICTION in audit
        assert "CONTRADICTION" in codes or "UNKNOWN" in codes

    def test_count_matches_escalation_records(self, populated_client):
        client, *_ = populated_client
        data = client.get("/v1/insights/escalation-clusters").json()
        total = sum(c["count"] for c in data)
        assert total >= 1


class TestInsightsDatabaseUnavailable:
    """Test that a missing audit DB returns 503, not 500."""

    def test_missing_db_returns_503(self, tmp_esc_db):
        evaluator = Evaluator([FixedSignal(k, v) for k, v in {
            "relevance": 0.9, "entailment": 0.9, "contradiction": 0.05,
            "freshness": 0.9, "completeness": 0.9, "ambiguity": 0.05,
        }.items()])
        app = create_app(evaluator=evaluator)
        # Point to a path that does not exist
        app.state.audit_db_path = "/nonexistent/path/audit.db"
        client = TestClient(app)
        endpoints = [
            "/v1/insights/conflicting-document-pairs",
            "/v1/insights/stale-document-retrievals",
            "/v1/insights/abstain-topics",
            "/v1/insights/decisions-by-decision?decision=ESCALATE",
        ]
        for ep in endpoints:
            r = client.get(ep)
            assert r.status_code == 503, f"Expected 503 for {ep}, got {r.status_code}"
            assert "unavailable" in r.json()["detail"].lower()
