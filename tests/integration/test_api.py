"""Integration tests for the FastAPI interface and central-adapter contract.

Model-backed (session-scoped engine fixture).
"""

import pytest

from fastapi.testclient import TestClient

from aegis_core.api import create_app
from aegis_core.central_adapter import (
    CentralAegisAdapter,
    evaluate_for_policy,
    DECISIONS,
)


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_evaluate_returns_four_signals(client):
    r = client.post("/v1/evaluate", json={
        "query": "How many casual leaves?",
        "answer": "Employees receive 18 casual leaves per year.",
        "evidence": ["Employees are entitled to 18 casual leaves per year."],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["decision_ready"] is True
    assert set(body["signals"].keys()) == {
        "relevance", "entailment", "contradiction", "completeness"
    }
    for name, sig in body["signals"].items():
        assert 0.0 <= sig["value"] <= 1.0, f"{name} out of range"
        assert isinstance(sig["reasons"], list)
    assert isinstance(body["reasons"], list) and body["reasons"]


def test_evaluate_with_evidence_metadata(client):
    r = client.post("/v1/evaluate", json={
        "query": "What is the refund period?",
        "answer": "Refunds within 30 days.",
        "evidence": [
            {"text": "Refunds within 30 days.", "source": "policy_v1", "version": "v1"},
            {"text": "Refunds within 45 days.", "source": "policy_v2", "version": "v2"},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    # Two versions of the same topic -> contradiction should fire.
    assert body["signals"]["contradiction"]["value"] > 0.3


def test_evaluate_empty_evidence(client):
    r = client.post("/v1/evaluate", json={
        "query": "How many casual leaves?",
        "answer": "Employees receive 18 casual leaves.",
        "evidence": [],
    })
    assert r.status_code == 200
    body = r.json()
    for name, sig in body["signals"].items():
        assert sig["value"] <= 0.05, f"{name} must be conservative"


# ------------------------------------------------------------------
# Central adapter contract
# ------------------------------------------------------------------
def test_adapter_payload_shape():
    adapter = CentralAegisAdapter()
    payload = adapter.run(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
    )
    assert payload["query"] == "How many casual leaves?"
    assert "signals" in payload
    assert "reasons" in payload
    assert "metadata" in payload
    # The adapter must NOT set a decision - that is the policy engine's job.
    assert "decision" not in payload
    assert "answerability_score" not in payload


def test_decision_labels_are_the_four():
    assert DECISIONS == ("ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN")


def test_evaluate_for_policy_function():
    # Models are process-wide singletons, so this reuses the
    # already-loaded models from the session fixture without a reload.
    payload = evaluate_for_policy(
        query="How many casual leaves?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
    )
    assert payload["signals"]["entailment"]["value"] > 0.7
