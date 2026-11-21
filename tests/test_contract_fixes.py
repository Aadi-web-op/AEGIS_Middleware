"""Regression tests for the API-contract issues found during frontend integration.

1. Claim reasons label evidence E1..En, 1-based, matching the passage order.
2. /v1/decisions keeps generation failures out of the decision counts.
3. The RAG workflow returns the generated answer, and claim spans index into it.
"""

from datetime import date

from fastapi.testclient import TestClient

from app.audit import AuditLogger
from app.core.evaluator import Evaluator
from app.escalation import EscalationQueue
from app.evidence.stubs import FixedSignal
from app.main import create_app
from app.rag.aegis_workflow import AEGISWorkflow
from app.rag.knowledge_base import KnowledgeBase
from app.schemas import ClaimStatus, EvaluateResponse

GOOD = dict(relevance=0.95, entailment=0.95, contradiction=0.02,
            freshness=0.9, completeness=0.9, ambiguity=0.04)


# ── 1. Evidence labels ──────────────────────────────────────────────────────

def test_supported_reason_labels_are_one_based():
    reason = Evaluator._claim_reason(
        {"supporting_evidence_indices": [1], "contradicting_evidence_indices": [0]},
        ClaimStatus.SUPPORTED,
        verified=True,
    )
    assert reason == "Stated by evidence E2. Evidence E1 says otherwise, so the sources disagree."


def test_contradicted_reason_labels_are_one_based():
    reason = Evaluator._claim_reason(
        {"supporting_evidence_indices": [], "contradicting_evidence_indices": [0, 2]},
        ClaimStatus.CONTRADICTED,
        verified=True,
    )
    assert reason == "Contradicted by evidence E1, E3."
    assert "E0" not in reason and "[0]" not in reason


# ── 2. Generation failures are not a decision ───────────────────────────────

def _client():
    evaluator = Evaluator([FixedSignal(n, v) for n, v in GOOD.items()])
    audit = AuditLogger(":memory:")
    app = create_app(evaluator, audit_logger=audit, escalation_queue=EscalationQueue(":memory:"))
    return TestClient(app), audit


def test_decision_counts_exclude_generation_failures():
    client, audit = _client()
    payload = {
        "query": "How many casual leaves can an employee take?",
        "answer": "Employees can take 18 casual leaves.",
        "evidence": [{"text": "Employees are entitled to 18 casual leaves.", "source": "p.pdf"}],
    }
    client.post("/v1/evaluate", json=payload)
    audit.log_generation_failure(query="Anything?", error="provider down")

    body = client.get("/v1/decisions").json()
    assert body["counts"] == {"ANSWER": 1}
    assert set(body["counts"]) <= {"ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"}
    assert body["generation_failures"] == 1
    # total still counts every logged request, so paging covers all rows.
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_no_generation_failures_reports_zero():
    client, _ = _client()
    assert client.get("/v1/decisions").json()["generation_failures"] == 0


# ── 3. RAG returns the generated answer ────────────────────────────────────

class _Provider:
    TEXT = "Remote sensing uses satellites to observe Earth."

    def generate(self, prompt, **kwargs):
        from app.providers.base import LLMResponse

        return LLMResponse(text=self.TEXT, provider="test-provider")


def test_rag_response_carries_generated_answer_and_spans_index_into_it():
    from app.ingestion.chunker import chunk_text

    kb = KnowledgeBase()
    kb.vector_store.add_chunks(
        chunk_text(
            text="Remote sensing uses satellites to observe Earth. " * 20,
            source="earth.pdf",
            chunk_size=30,
            overlap=5,
            date=date.today().isoformat(),
            version="1.0",
        )
    )
    evaluator = Evaluator([FixedSignal(n, v) for n, v in GOOD.items()])
    response = AEGISWorkflow(kb, _Provider(), evaluator).run("What is remote sensing?")

    assert isinstance(response, EvaluateResponse)
    # Exactly the provider's generated text: nothing rewritten or invented.
    assert response.answer == _Provider.TEXT
    for claim in response.claims:
        if claim.span is not None:
            start, end = claim.span
            assert response.answer[start:end].rstrip(".") == claim.claim.rstrip(".")


def test_rag_empty_knowledge_base_still_returns_answer_text():
    evaluator = Evaluator([FixedSignal(n, v) for n, v in GOOD.items()])

    class _NoLLM:
        def generate(self, prompt, **kwargs):
            raise AssertionError("LLM must not run without evidence")

    response = AEGISWorkflow(KnowledgeBase(), _NoLLM(), evaluator).run("Anything?")
    assert response.answer == "No answer generated: no evidence is available."


def test_evaluate_endpoint_leaves_answer_unset():
    client, _ = _client()
    body = client.post(
        "/v1/evaluate",
        json={"query": "Q?", "answer": "A.", "evidence": [{"text": "A."}]},
    ).json()
    assert body.get("answer") is None
