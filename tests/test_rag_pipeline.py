from app.ingestion.chunker import chunk_text
from app.retrieval.vector_store import VectorStore
from app.rag.pipeline import RAGPipeline


def test_rag_pipeline_retrieves_evidence():
    chunks = chunk_text(
        text=(
            "Remote sensing uses sensors to collect information "
            "about objects or areas from a distance. "
        )
        * 20,
        source="remote_sensing.txt",
        chunk_size=30,
        overlap=5,
    )

    store = VectorStore()
    store.add_chunks(chunks)

    pipeline = RAGPipeline(store)

    result = pipeline.retrieve(
        "What is remote sensing?",
        top_k=3,
    )

    assert result.query == "What is remote sensing?"
    assert len(result.evidence) > 0
    assert result.context
    assert "Remote sensing" in result.context