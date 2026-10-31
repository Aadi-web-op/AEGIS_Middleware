import os
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.evaluator import Evaluator
from app.escalation import (
    DuplicateEscalationError,
    EscalationNotFoundError,
    EscalationQueue,
    EscalationStatus,
    InvalidStatusTransitionError,
)
from app.evidence.stubs import FixedSignal
from app.main import create_app
from app.rag.aegis_workflow import AEGISWorkflow
from app.schemas import Decision, EvaluateRequest, EvidenceItem, RecommendedAction


@pytest.fixture
def temp_db_path(tmp_path):
    return tmp_path / f"test_escalations_{uuid.uuid4().hex[:8]}.db"


@pytest.fixture
def queue(temp_db_path):
    q = EscalationQueue(temp_db_path)
    yield q
    q.close()


def test_enqueue_and_get_by_id(queue):
    rec = queue.enqueue(
        request_id="req-101",
        reason="Evidence contradicts previous guidelines",
        decision="ESCALATE",
        query="What is the vacation policy?",
        answer="You get 15 days.",
        notes="Flagged for policy HR review",
    )
    assert rec.escalation_id.startswith("esc-")
    assert rec.request_id == "req-101"
    assert rec.reason == "Evidence contradicts previous guidelines"
    assert rec.decision == "ESCALATE"
    assert rec.status == EscalationStatus.PENDING
    assert rec.created_at
    assert rec.updated_at

    fetched = queue.get_by_id(rec.escalation_id)
    assert fetched.escalation_id == rec.escalation_id
    assert fetched.request_id == "req-101"
    assert fetched.status == EscalationStatus.PENDING


def test_persistence_across_restarts(temp_db_path):
    # Enqueue a record in first queue instance
    q1 = EscalationQueue(temp_db_path)
    rec1 = q1.enqueue(
        request_id="req-persist-1",
        reason="High ambiguity",
        decision="ESCALATE",
        query="Ambiguous question?",
        answer="Ambiguous answer.",
    )
    q1.update_status(rec1.escalation_id, EscalationStatus.IN_REVIEW, notes="Assigned to reviewer")
    q1.close()

    # Simulate restart by instantiating a new queue instance pointing to same SQLite database
    q2 = EscalationQueue(temp_db_path)
    fetched = q2.get_by_id(rec1.escalation_id)
    assert fetched.escalation_id == rec1.escalation_id
    assert fetched.request_id == "req-persist-1"
    assert fetched.status == EscalationStatus.IN_REVIEW
    assert fetched.notes == "Assigned to reviewer"

    # Further updates in second session
    q2.update_status(rec1.escalation_id, EscalationStatus.RESOLVED, notes="Resolved by reviewer")
    q2.close()

    # Third session verification
    q3 = EscalationQueue(temp_db_path)
    fetched_final = q3.get_by_id(rec1.escalation_id)
    assert fetched_final.status == EscalationStatus.RESOLVED
    assert fetched_final.notes == "Resolved by reviewer"
    q3.close()


def test_empty_queue_safety(queue):
    # Empty list
    records = queue.list_escalations()
    assert records == []

    # Filtered on empty queue
    pending = queue.list_escalations(status=EscalationStatus.PENDING)
    assert pending == []

    # Get non-existent ID raises EscalationNotFoundError
    with pytest.raises(EscalationNotFoundError):
        queue.get_by_id("non-existent-id")

    # Get non-existent request ID returns None
    assert queue.get_by_request_id("no-such-request") is None


def test_duplicate_handling(queue):
    rec1 = queue.enqueue(
        request_id="req-dup",
        reason="Initial conflict",
        raise_on_duplicate=False,
    )
    assert rec1.request_id == "req-dup"

    # Idempotent enqueue returns the existing record
    rec2 = queue.enqueue(
        request_id="req-dup",
        reason="Second conflict attempt",
        raise_on_duplicate=False,
    )
    assert rec2.escalation_id == rec1.escalation_id

    # Strict enqueue raises DuplicateEscalationError
    with pytest.raises(DuplicateEscalationError) as exc_info:
        queue.enqueue(
            request_id="req-dup",
            reason="Third conflict attempt",
            raise_on_duplicate=True,
        )
    assert "Active escalation already exists" in str(exc_info.value)

    # After resolution, a new escalation for the same request_id can be queued
    queue.update_status(rec1.escalation_id, EscalationStatus.RESOLVED)
    rec3 = queue.enqueue(
        request_id="req-dup",
        reason="Follow-up issue after resolution",
        raise_on_duplicate=True,
    )
    assert rec3.escalation_id != rec1.escalation_id
    assert rec3.status == EscalationStatus.PENDING


def test_status_transitions_valid_and_invalid(queue):
    rec = queue.enqueue(
        request_id="req-transitions",
        reason="Needs human review",
    )
    assert rec.status == EscalationStatus.PENDING

    # pending -> in_review
    rec_review = queue.update_status(rec.escalation_id, EscalationStatus.IN_REVIEW, notes="Started review")
    assert rec_review.status == EscalationStatus.IN_REVIEW
    assert rec_review.notes == "Started review"

    # in_review -> resolved
    rec_resolved = queue.update_status(rec.escalation_id, EscalationStatus.RESOLVED, notes="Approved")
    assert rec_resolved.status == EscalationStatus.RESOLVED

    # resolved is terminal -> cannot transition to in_review or pending
    with pytest.raises(InvalidStatusTransitionError) as exc:
        queue.update_status(rec.escalation_id, EscalationStatus.IN_REVIEW)
    assert "Cannot transition escalation from resolved to in_review" in str(exc.value)

    with pytest.raises(InvalidStatusTransitionError):
        queue.update_status(rec.escalation_id, EscalationStatus.PENDING)

    # Invalid status name
    with pytest.raises(InvalidStatusTransitionError):
        queue.update_status(rec.escalation_id, "unknown_status")


def test_sanitize_secrets_in_escalations(queue, monkeypatch):
    monkeypatch.setenv("TEST_COMPANY_API_KEY", "super_secret_auth_token_xyz987")

    rec = queue.enqueue(
        request_id="req-secret-leak",
        reason="Auth failure with Bearer abc1234567890 token and key: super_secret_auth_token_xyz987",
        query="Show me gsk_9999888877776666",
        answer="Returned api_key='sk-test-secret-123456'",
        notes="Reviewer noted Bearer mytokenxyz123456",
    )

    assert "Bearer abc1234567890" not in rec.reason
    assert "[REDACTED]" in rec.reason
    assert "super_secret_auth_token_xyz987" not in rec.reason

    assert "gsk_" not in rec.query
    assert "[REDACTED]" in rec.query

    assert "sk-test-secret-123456" not in rec.answer
    assert "[REDACTED]" in rec.answer

    assert "Bearer mytokenxyz123456" not in rec.notes
    assert "[REDACTED]" in rec.notes


# API Endpoint Tests
def test_api_escalation_lifecycle(temp_db_path):
    queue = EscalationQueue(temp_db_path)
    evaluator = Evaluator([FixedSignal("relevance", 0.95)])
    app = create_app(evaluator=evaluator, escalation_queue=queue)
    client = TestClient(app)

    # 1. Initially empty pending list
    res = client.get("/v1/escalations/pending")
    assert res.status_code == 200
    assert res.json() == []

    # 2. Create escalation via POST /v1/escalations
    create_payload = {
        "request_id": "api-req-1",
        "reason": "Direct user escalation request",
        "decision": "ESCALATE",
        "query": "Is remote work permitted?",
        "answer": "Yes with manager approval.",
        "notes": "Requires HR signoff",
    }
    res_create = client.post("/v1/escalations", json=create_payload)
    assert res_create.status_code == 201
    created_data = res_create.json()
    esc_id = created_data["escalation_id"]
    assert created_data["status"] == "pending"
    assert created_data["request_id"] == "api-req-1"

    # 3. Duplicate POST should return 409 Conflict
    res_dup = client.post("/v1/escalations", json=create_payload)
    assert res_dup.status_code == 409
    assert "Active escalation already exists" in res_dup.json()["detail"]

    # 4. GET /v1/escalations/pending should now contain this item
    res_pending = client.get("/v1/escalations/pending")
    assert res_pending.status_code == 200
    pending_list = res_pending.json()
    assert len(pending_list) == 1
    assert pending_list[0]["escalation_id"] == esc_id

    # 5. GET /v1/escalations with query filters
    res_list = client.get(f"/v1/escalations?request_id=api-req-1&status=pending")
    assert res_list.status_code == 200
    assert len(res_list.json()) == 1

    # 6. GET /v1/escalations/{id}
    res_get = client.get(f"/v1/escalations/{esc_id}")
    assert res_get.status_code == 200
    assert res_get.json()["escalation_id"] == esc_id

    # 7. GET invalid ID returns 404
    res_404 = client.get("/v1/escalations/non-existent-esc")
    assert res_404.status_code == 404

    # 8. PATCH /v1/escalations/{id} to transition to in_review
    res_update = client.patch(
        f"/v1/escalations/{esc_id}",
        json={"status": "in_review", "notes": "Under review by Ops"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["status"] == "in_review"
    assert res_update.json()["notes"] == "Under review by Ops"

    # 9. Verify pending list is now empty
    res_pending_after = client.get("/v1/escalations/pending")
    assert res_pending_after.json() == []

    # 10. PUT /v1/escalations/{id} to transition to dismissed
    res_dismiss = client.put(
        f"/v1/escalations/{esc_id}",
        json={"status": "dismissed", "notes": "False alarm"},
    )
    assert res_dismiss.status_code == 200
    assert res_dismiss.json()["status"] == "dismissed"

    # 11. Invalid transition from dismissed back to pending returns 400
    res_invalid_transition = client.patch(
        f"/v1/escalations/{esc_id}",
        json={"status": "pending"},
    )
    assert res_invalid_transition.status_code == 400
    assert "Cannot transition" in res_invalid_transition.json()["detail"]

    # 12. Update non-existent ID returns 404
    res_update_missing = client.patch(
        "/v1/escalations/unknown-id",
        json={"status": "resolved"},
    )
    assert res_update_missing.status_code == 404


def test_workflow_auto_escalation_integration(temp_db_path):
    queue = EscalationQueue(temp_db_path)
    # Configure evaluator with high contradiction so it forces ESCALATE decision
    evaluator = Evaluator([
        FixedSignal("relevance", 0.95),
        FixedSignal("entailment", 0.95),
        FixedSignal("contradiction", 0.9),  # triggers contradiction reason & ESCALATE
        FixedSignal("freshness", 0.9),
        FixedSignal("completeness", 0.9),
        FixedSignal("ambiguity", 0.04),
    ])
    app = create_app(evaluator=evaluator, escalation_queue=queue)
    client = TestClient(app)

    # Send evaluation payload that will be escalated
    payload = {
        "query": "How many casual leaves can an employee take?",
        "answer": "Employees can take 18 casual leaves.",
        "evidence": [{
            "text": "Employees are entitled to 18 casual leaves.",
            "source": "policy_2026.pdf",
            "date": "2026-08-01",
            "version": "v3",
        }],
        "profile": "standard",
    }
    r = client.post("/v1/evaluate", json=payload)
    assert r.status_code == 200
    resp_data = r.json()
    assert resp_data["decision"] == "ESCALATE"

    # Verify case was auto-enqueued in escalation queue
    pending = queue.list_escalations(status=EscalationStatus.PENDING)
    assert len(pending) == 1
    escalated_case = pending[0]
    assert escalated_case.request_id == resp_data["request_id"]
    assert escalated_case.decision == "ESCALATE"
    assert "contradiction" in escalated_case.reason.lower()
    assert "Auto-escalated by policy" in escalated_case.notes
