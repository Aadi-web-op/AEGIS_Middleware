import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.audit.logger import AuditLogger, default_audit_db_path, sanitize_secrets
from app.main import create_app
from app.providers.base import ProviderError
from app.providers.fake import FakeProvider
from app.rag.knowledge_base import KnowledgeBase
from app.schemas import (
    Decision,
    EvaluateRequest,
    EvaluateResponse,
    EvidenceItem,
    Reason,
    ReasonCode,
    RecommendedAction,
    Signals,
)
from fastapi.testclient import TestClient


@pytest.fixture
def memory_logger():
    logger = AuditLogger(":memory:")
    yield logger
    logger.close()


@pytest.fixture
def file_logger(tmp_path):
    db_file = tmp_path / "test_audit.db"
    logger = AuditLogger(str(db_file))
    yield logger
    logger.close()


def make_eval_pair():
    req = EvaluateRequest(
        query="What is the leave policy?",
        answer="Staff receive 18 days of leave.",
        evidence=[EvidenceItem(text="Staff receive 18 days.", source="policy.pdf")],
        profile="standard",
    )
    res = EvaluateResponse(
        request_id="req-12345",
        decision=Decision.ANSWER,
        answerability_score=0.95,
        signals=Signals(relevance=0.98, entailment=0.92, contradiction=0.01),
        reasons=[Reason(code=ReasonCode.LOW_RELEVANCE, message="Looks relevant")],
        recommended_action=RecommendedAction.RETURN_ANSWER,
        policy_version="1.0.0",
        latency_ms=12.5,
    )
    return req, res


def test_audit_record_creation_and_persistence(file_logger):
    req, res = make_eval_pair()
    rec_id = file_logger.log_evaluation(req, res, generation_success=True)

    assert rec_id == "req-12345"
    record = file_logger.get_record("req-12345")
    assert record is not None
    assert record["request_id"] == "req-12345"
    assert record["decision"] == "ANSWER"
    assert record["answerability_score"] == 0.95
    assert record["query"] == "What is the leave policy?"
    assert record["answer"] == "Staff receive 18 days of leave."
    assert record["profile"] == "standard"
    assert record["generation_success"] == 1
    assert record["latency_ms"] == 12.5
    assert record["signals"]["relevance"] == 0.98
    assert "LOW_RELEVANCE" in record["reason_codes"]
    assert record["error_message"] is None


def test_audit_record_with_in_memory_db(memory_logger):
    req, res = make_eval_pair()
    memory_logger.log_evaluation(req, res)

    record = memory_logger.get_record("req-12345")
    assert record is not None
    assert record["decision"] == "ANSWER"

    records = memory_logger.list_records(limit=10)
    assert len(records) == 1
    assert records[0]["request_id"] == "req-12345"


def test_audit_generation_failure(memory_logger):
    rec_id = memory_logger.log_generation_failure(
        query="Explain remote sensing",
        error="groq: HTTP 503: Service Unavailable",
        profile="strict",
    )
    assert rec_id is not None

    record = memory_logger.get_record(rec_id)
    assert record is not None
    assert record["query"] == "Explain remote sensing"
    assert record["generation_success"] == 0
    assert record["error_message"] == "groq: HTTP 503: Service Unavailable"
    assert record["decision"] is None
    assert record["answerability_score"] is None


def test_never_stores_secrets_or_api_keys(memory_logger, monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", "super_secret_groq_key_12345")

    sensitive_query = "My key is Bearer gsk_abcdef1234567890 and super_secret_groq_key_12345"
    sensitive_answer = "Stored with api_key: 'gsk_secret987654321'"

    req = EvaluateRequest(
        query=sensitive_query,
        answer=sensitive_answer,
        evidence=[],
    )
    res = EvaluateResponse(
        request_id="req-safe",
        decision=Decision.ABSTAIN,
        answerability_score=0.0,
        signals=Signals(),
        reasons=[],
        recommended_action=RecommendedAction.ABSTAIN,
        policy_version="1.0.0",
        latency_ms=1.0,
    )
    memory_logger.log_evaluation(req, res)

    record = memory_logger.get_record("req-safe")
    assert record is not None
    assert "super_secret_groq_key_12345" not in record["query"]
    assert "gsk_abcdef1234567890" not in record["query"]
    assert "gsk_secret987654321" not in record["answer"]
    assert "[REDACTED]" in record["query"]
    assert "[REDACTED]" in record["answer"]


def test_sanitize_secrets_handles_none_and_empty():
    assert sanitize_secrets(None) is None
    assert sanitize_secrets("") == ""
    assert sanitize_secrets("normal text") == "normal text"


def test_error_handling_gracefully_degrades():
    logger = AuditLogger(":memory:")
    # Simulate a broken database by closing the shared connection
    logger.close()

    req, res = make_eval_pair()
    # Must not raise an exception; returns None on failure
    assert logger.log_evaluation(req, res) is None
    assert logger.log_generation_failure("query", "error") is None
    assert logger.get_record("any") is None
    assert logger.list_records() == []


def test_default_audit_db_path(monkeypatch):
    monkeypatch.delenv("AEGIS_AUDIT_DB_PATH", raising=False)
    p = default_audit_db_path()
    assert str(p).endswith("audit.db")

    monkeypatch.setenv("AEGIS_AUDIT_DB_PATH", "custom/test.db")
    assert default_audit_db_path() == Path("custom/test.db")


def test_audit_integrated_into_evaluate_endpoint():
    audit_logger = AuditLogger(":memory:")
    app = create_app(audit_logger=audit_logger)
    client = TestClient(app)

    payload = {
        "query": "How many leaves per year?",
        "answer": "18 leaves per year.",
        "evidence": [{
            "text": "Employees get 18 leaves per year.",
            "source": "leave.pdf",
            "date": "2026-01-01",
            "version": "1.0",
        }],
        "profile": "standard",
    }
    r = client.post("/v1/evaluate", json=payload)
    assert r.status_code == 200
    req_id = r.json()["request_id"]

    record = audit_logger.get_record(req_id)
    assert record is not None
    assert record["request_id"] == req_id
    assert record["decision"] == r.json()["decision"]
    assert record["query"] == payload["query"]
    audit_logger.close()


def test_audit_integrated_into_rag_ask_success():
    from app.ingestion.chunker import chunk_text

    audit_logger = AuditLogger(":memory:")
    app = create_app(audit_logger=audit_logger)
    client = TestClient(app)

    kb = KnowledgeBase()
    chunks = chunk_text(
        text="Remote sensing observes Earth using satellite sensors. " * 20,
        source="satellites.pdf",
        chunk_size=30,
        overlap=5,
    )
    kb.vector_store.add_chunks(chunks)
    client.app.state.rag_knowledge_base = kb
    client.app.state.rag_provider = FakeProvider(["Satellites collect remote sensing data."])

    r = client.post("/v1/rag/ask", json={"question": "How does remote sensing work?"})
    assert r.status_code == 200
    req_id = r.json()["request_id"]

    record = audit_logger.get_record(req_id)
    assert record is not None
    assert record["generation_success"] == 1
    assert record["query"] == "How does remote sensing work?"
    assert record["answer"] == "Satellites collect remote sensing data."
    audit_logger.close()


def test_audit_integrated_into_rag_ask_failure():
    from app.ingestion.chunker import chunk_text

    audit_logger = AuditLogger(":memory:")
    app = create_app(audit_logger=audit_logger)
    client = TestClient(app)

    kb = KnowledgeBase()
    chunks = chunk_text(
        text="Sample information about Earth. " * 20,
        source="earth.pdf",
        chunk_size=30,
        overlap=5,
    )
    kb.vector_store.add_chunks(chunks)
    client.app.state.rag_knowledge_base = kb
    client.app.state.rag_provider = FakeProvider(fail=True)

    r = client.post("/v1/rag/ask", json={"question": "What is remote sensing?"})
    assert r.status_code == 503

    records = audit_logger.list_records(limit=1)
    assert len(records) == 1
    assert records[0]["generation_success"] == 0
    assert "simulated failure" in records[0]["error_message"]
    audit_logger.close()
