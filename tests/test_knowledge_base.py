
from app.rag.knowledge_base import KnowledgeBase


def test_pdf_ingestion_and_retrieval(tmp_path):
    from unittest.mock import patch

    kb = KnowledgeBase()

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"placeholder")

    sample_text = (
        "Remote sensing collects information about "
        "Earth using sensors on satellites. "
    ) * 30

    with patch(
        "app.rag.knowledge_base.load_pdf",
        return_value=sample_text,
    ):
        chunks_added = kb.ingest_pdf(
            str(pdf),
            date="2026-10-19",
            version="1.0",
            chunk_size=30,
            overlap=5,
        )

    assert chunks_added > 0

    result = kb.query("What is remote sensing?", top_k=3)

    assert result.query == "What is remote sensing?"
    assert result.evidence
    assert result.context
    assert all(
        chunk.source == "sample.pdf"
        for chunk in result.evidence
    )
