
from unittest.mock import patch

from app.rag.knowledge_base import KnowledgeBase
from app.providers.base import LLMProvider, LLMResponse


class StubProvider(LLMProvider):
    name = "test-provider"

    def generate(
        self,
        prompt,
        *,
        system=None,
        temperature=0.0,
        max_tokens=512,
    ):
        assert "Remote sensing" in prompt
        assert system is not None

        return LLMResponse(
            text="Remote sensing uses sensors to collect information.",
            provider=self.name,
        )


def test_rag_generates_answer_from_retrieved_evidence(tmp_path):
    kb = KnowledgeBase()

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"placeholder")

    sample_text = (
        "Remote sensing uses sensors to collect information "
        "about Earth from a distance. "
    ) * 30

    with patch(
        "app.rag.knowledge_base.load_pdf",
        return_value=sample_text,
    ):
        kb.ingest_pdf(
            str(pdf),
            chunk_size=30,
            overlap=5,
        )

    result = kb.answer(
        "What is remote sensing?",
        provider=StubProvider(),
        top_k=3,
    )

    assert result.answer
    assert result.provider == "test-provider"
    assert result.evidence
    assert "Remote sensing" in result.context
    assert result.fallback_used is False
