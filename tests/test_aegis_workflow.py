
from datetime import date

from app.rag.aegis_workflow import AEGISWorkflow
from app.rag.knowledge_base import KnowledgeBase
from app.schemas import EvaluateRequest, EvaluateResponse


class FakeEvaluator:
    def __init__(self):
        self.request = None

    def evaluate(self, request):
        self.request = request
        # Verify that the workflow supplies the actual request schema.
        assert isinstance(request, EvaluateRequest)
        return "evaluation-called"


class FakeProvider:
    def generate(self, prompt, **kwargs):
        from app.providers.base import LLMResponse

        return LLMResponse(
            text="Remote sensing uses sensors to observe Earth.",
            provider="test-provider",
        )


def test_workflow_passes_rag_answer_and_metadata_to_evaluator():
    from unittest.mock import patch
    from app.ingestion.chunker import chunk_text

    kb = KnowledgeBase()
    chunks = chunk_text(
        text=("Remote sensing uses satellites to observe Earth. " * 20),
        source="earth.pdf",
        chunk_size=30,
        overlap=5,
        date=date.today().isoformat(),
        version="1.0",
    )
    kb.vector_store.add_chunks(chunks)

    evaluator = FakeEvaluator()
    workflow = AEGISWorkflow(kb, FakeProvider(), evaluator)

    result = workflow.run("What is remote sensing?")

    assert result == "evaluation-called"
    assert isinstance(evaluator.request, EvaluateRequest)
    assert evaluator.request.query == "What is remote sensing?"
    assert evaluator.request.answer
    assert evaluator.request.evidence
    assert evaluator.request.evidence[0].source == "earth.pdf"
    assert evaluator.request.evidence[0].version == "1.0"
    assert evaluator.request.evidence[0].date == date.today()


def test_empty_knowledge_base_skips_llm():
    kb = KnowledgeBase()
    evaluator = FakeEvaluator()

    class MustNotRunProvider:
        def generate(self, prompt, **kwargs):
            raise AssertionError("LLM must not run without evidence")

    workflow = AEGISWorkflow(
        kb,
        MustNotRunProvider(),
        evaluator,
    )

    workflow.run("What is remote sensing?")

    assert evaluator.request.evidence == []
    assert evaluator.request.answer
