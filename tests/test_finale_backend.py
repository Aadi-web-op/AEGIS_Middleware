import asyncio
from contextlib import aclosing
import json

from fastapi.testclient import TestClient

from app.audit import AuditLogger
from app.core.evaluator import Evaluator
from app.core.policy import decide
from app.core.scoring import compute_score
from app.escalation import EscalationQueue
from app.evidence.stubs import FixedSignal
from app.graph.events import GraphEvents
from app.main import create_app
from app.schemas import Signals


def _app(tmp_path, monkeypatch, **overrides):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    values = dict(relevance=0.95, entailment=0.95, contradiction=0.8,
                  freshness=0.90, completeness=0.90, ambiguity=0.04)
    values.update(overrides)
    return create_app(
        Evaluator([FixedSignal(name, value) for name, value in values.items()]),
        audit_logger=AuditLogger(tmp_path / "audit.db"),
        escalation_queue=EscalationQueue(tmp_path / "escalations.db"),
    )


_REQUEST = {"query": "How much leave?", "answer": "12 days", "evidence": [{"text": "12 days"}]}


def test_counterfactual_uses_actual_policy_at_the_veto_boundary(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    result = TestClient(app).post("/v1/evaluate", json=_REQUEST).json()

    assert result["decision"] == "ESCALATE"
    explanation = result["counterfactual"]
    assert explanation["score_only_decision"] == "ANSWER"
    assert explanation["policy_reasons"][0]["code"] == "CONTRADICTION"
    assert explanation["contributions"]["agreement"] == 0.03
    change = explanation["minimum_change"]
    assert (change["signal"], change["target"], change["resulting_decision"]) == (
        "contradiction", 0.5999, "ANSWER",
    )
    config = app.state.evaluator.config
    signals = Signals(**{**result["signals"], "contradiction": 0.6})
    assert decide(signals, compute_score(signals, config.weights), config.get_profile("standard"), 1).decision == "ESCALATE"


def test_two_active_vetoes_have_no_single_signal_fix(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, entailment=0.2)
    result = TestClient(app).post("/v1/evaluate", json=_REQUEST).json()
    assert result["decision"] == "ESCALATE"
    assert {r["code"] for r in result["counterfactual"]["policy_reasons"]} == {
        "CONTRADICTION", "UNSUPPORTED_CLAIM",
    }
    assert result["counterfactual"]["minimum_change"] is None


def test_uploaded_revision_can_be_retried_without_reindexing_when_neo4j_is_off(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)

    class MemoryIndex:
        def __init__(self):
            self.chunks = []

        def add_chunks(self, chunks):
            self.chunks.extend(chunks)

    monkeypatch.setattr("app.rag.knowledge_base.VectorStore", MemoryIndex)
    monkeypatch.setattr("app.rag.knowledge_base.load_pdf", lambda path: "Paid leave is 12 days.")
    client = TestClient(app)
    kwargs = {
        "content": b"%PDF-1.7",
        "headers": {"Content-Type": "application/pdf"},
        "params": {"source": "leave-policy.pdf", "version": "v1"},
    }
    first = client.post("/v1/rag/ingest/upload", **kwargs)
    second = client.post("/v1/rag/ingest/upload", **kwargs)
    assert first.status_code == second.status_code == 200
    assert first.json()["change_detection"] == {"status": "unavailable"}
    assert first.json()["chunks_added"] == 1
    assert second.json()["chunks_added"] == 0
    assert first.json()["document"] == second.json()["document"]
    chunk, = app.state.rag_knowledge_base.vector_store.chunks
    assert chunk.document_content_hash == first.json()["document"]["content_hash"]


def test_live_stream_publishes_and_replays_with_bounded_history():
    async def exercise():
        events = GraphEvents(capacity=2, heartbeat_seconds=0.01)
        async with aclosing(events.stream()) as live:
            assert await anext(live) == ": connected\n\n"
            await asyncio.to_thread(events.publish, {"request_id": "r1"})
            first = await asyncio.wait_for(anext(live), 1)
            assert json.loads(first.split("data: ", 1)[1]) == {"request_id": "r1"}
            first_id = first.splitlines()[0].removeprefix("id: ")

        for request_id in ("r2", "r3", "r4"):
            events.publish({"request_id": request_id})
        async with aclosing(events.stream(first_id)) as replay:
            assert await anext(replay) == ": connected\n\n"
            assert "event: reset" in await anext(replay)
            assert '"request_id":"r3"' in await anext(replay)
            assert '"request_id":"r4"' in await anext(replay)
            assert await anext(replay) == ": keep-alive\n\n"

    asyncio.run(exercise())
