from app.ingestion.chunker import chunk_text
from app.retrieval.vector_store import VectorStore


def test_chunking():
    text = "This is a test document. " * 200

    chunks = chunk_text(
        text=text,
        source="test_document.txt",
        chunk_size=50,
        overlap=10,
    )

    assert len(chunks) > 1
    assert chunks[0].source == "test_document.txt"
    assert chunks[0].chunk_id == 0


def test_vector_store():
    chunks = chunk_text(
        text="Python is a programming language. " * 20,
        source="test.txt",
        chunk_size=20,
        overlap=5,
    )

    store = VectorStore()
    store.add_chunks(chunks)

    results = store.search(
        "What is Python?",
        top_k=2,
    )

    assert len(results) > 0
    assert "Python" in results[0][0].text