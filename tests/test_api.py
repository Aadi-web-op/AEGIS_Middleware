from fastapi.testclient import TestClient

from app.core.evaluator import Evaluator
from app.evidence.stubs import FixedSignal
from app.main import create_app

PAYLOAD = {
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


def client_with(**signal_values) -> TestClient:
    values = dict(relevance=0.95, entailment=0.95, contradiction=0.02,
                  freshness=0.9, completeness=0.9, ambiguity=0.04)
    values.update(signal_values)
    evaluator = Evaluator([FixedSignal(name, v) for name, v in values.items()])
    return TestClient(create_app(evaluator))


def test_health():
    r = client_with().get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["signals"]) == {"relevance", "entailment", "contradiction",
                                    "freshness", "completeness", "ambiguity"}


def test_config_lists_profiles():
    body = client_with().get("/v1/config").json()
    assert set(body["profiles"]) == {"lenient", "standard", "strict"}


def test_evaluate_returns_answer():
    r = client_with().post("/v1/evaluate", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "ANSWER"
    assert body["recommended_action"] == "return_answer"
    assert body["request_id"]


def test_no_evidence_abstains():
    r = client_with().post("/v1/evaluate", json={**PAYLOAD, "evidence": []})
    assert r.status_code == 200
    assert r.json()["decision"] == "ABSTAIN"


def test_contradiction_escalates_through_the_api():
    r = client_with(contradiction=0.9).post("/v1/evaluate", json=PAYLOAD)
    assert r.json()["decision"] == "ESCALATE"


def test_strict_profile_changes_the_decision():
    client = client_with(relevance=0.9, entailment=0.9, contradiction=0.1,
                         freshness=0.8, completeness=0.8, ambiguity=0.1)
    standard = client.post("/v1/evaluate", json=PAYLOAD).json()
    strict = client.post("/v1/evaluate", json={**PAYLOAD, "profile": "strict"}).json()
    assert standard["decision"] == "ANSWER"
    assert strict["decision"] == "CAVEAT"


def test_empty_query_is_422():
    r = client_with().post("/v1/evaluate", json={**PAYLOAD, "query": ""})
    assert r.status_code == 422


def test_missing_answer_is_422():
    body = {k: v for k, v in PAYLOAD.items() if k != "answer"}
    assert client_with().post("/v1/evaluate", json=body).status_code == 422


def test_invalid_date_is_422():
    bad = {**PAYLOAD, "evidence": [{"text": "x", "date": "not-a-date"}]}
    assert client_with().post("/v1/evaluate", json=bad).status_code == 422


def test_unknown_profile_is_422_with_helpful_message():
    r = client_with().post("/v1/evaluate", json={**PAYLOAD, "profile": "paranoid"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "paranoid" in detail and "standard" in detail


def test_each_response_gets_a_new_request_id():
    client = client_with()
    a = client.post("/v1/evaluate", json=PAYLOAD).json()["request_id"]
    b = client.post("/v1/evaluate", json=PAYLOAD).json()["request_id"]
    assert a != b


def test_cors_allows_the_frontend_origin():
    r = client_with().options(
        "/v1/evaluate",
        headers={"Origin": "http://localhost:5173",
                 "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_rag_ask_empty_question_is_422():
    client = client_with()
    r = client.post("/v1/rag/ask", json={"question": "   "})
    assert r.status_code == 422


def test_rag_ask_empty_kb_is_409():
    client = client_with()
    r = client.post("/v1/rag/ask", json={"question": "What is remote sensing?"})
    assert r.status_code == 409
    assert "Knowledge base is empty" in r.json()["detail"]


def test_rag_ask_with_provider():
    from app.ingestion.chunker import chunk_text
    from app.providers.fake import FakeProvider
    from app.rag.knowledge_base import KnowledgeBase

    client = client_with()
    kb = KnowledgeBase()
    chunks = chunk_text(
        text="Remote sensing gathers info about Earth from distance. " * 20,
        source="doc.pdf",
        chunk_size=30,
        overlap=5,
    )
    kb.vector_store.add_chunks(chunks)
    client.app.state.rag_knowledge_base = kb
    client.app.state.rag_provider = FakeProvider(["Remote sensing uses satellites."])

    r = client.post("/v1/rag/ask", json={"question": "What is remote sensing?"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "ANSWER"
    assert "answerability_score" in body
    assert "signals" in body

    