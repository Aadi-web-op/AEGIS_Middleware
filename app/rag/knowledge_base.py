
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.graph.document_versions import DocumentRevision
from app.graph.identity import content_hash
from app.ingestion.loader import load_pdf
from app.ingestion.chunker import chunk_text
from app.retrieval.vector_store import VectorStore
from app.rag.pipeline import RAGPipeline, RAGResult
from app.providers.base import LLMProvider, LLMResponse


@dataclass
class RAGAnswer:
    """Baseline RAG answer and its retrieved evidence."""

    query: str
    answer: str
    provider: str
    evidence: list
    context: str
    fallback_used: bool = False


class KnowledgeBase:
    """Ingest PDFs, retrieve evidence and generate baseline answers."""

    def __init__(self):
        self.vector_store = VectorStore()
        self.pipeline = RAGPipeline(self.vector_store)
        self.document_count = 0
        self._index_lock = Lock()
        self._indexed_revisions: set[str] = set()

    def ingest_pdf(
        self,
        pdf_path: str,
        date: str | None = None,
        version: str | None = None,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> int:
        """Extract, chunk and index a PDF."""

        _, chunks_added = self.ingest_document(pdf_path, date, version, chunk_size, overlap)
        return chunks_added

    def ingest_document(
        self,
        pdf_path: str,
        date: str | None = None,
        version: str | None = None,
        chunk_size: int = 500,
        overlap: int = 50,
        *,
        source: str | None = None,
    ) -> tuple[DocumentRevision, int]:
        path = Path(pdf_path)

        if not path.is_file():
            raise FileNotFoundError(f"PDF not found: {path}")

        text = load_pdf(str(path))

        if not text.strip():
            raise ValueError(
                f"No text could be extracted from {path.name}"
            )

        revision = DocumentRevision(source or path.name, version, content_hash(text), date)
        chunks = chunk_text(
            text=text,
            source=revision.source,
            chunk_size=chunk_size,
            overlap=overlap,
            date=date,
            version=version,
            document_content_hash=revision.content_hash,
        )

        with self._index_lock:
            if revision.id in self._indexed_revisions:
                return revision, 0
            self.vector_store.add_chunks(chunks)
            self._indexed_revisions.add(revision.id)
            self.document_count += 1
        return revision, len(chunks)

    def query(
        self,
        question: str,
        top_k: int = 5,
    ) -> RAGResult:
        """Retrieve evidence relevant to a question."""

        if not question.strip():
            raise ValueError("Question cannot be empty.")

        with self._index_lock:
            if self.vector_store.index.ntotal == 0:
                raise ValueError("Knowledge base is empty. Ingest a PDF first.")
            return self.pipeline.retrieve(query=question, top_k=top_k)

    def answer(
        self,
        question: str,
        provider: LLMProvider,
        top_k: int = 5,
    ) -> RAGAnswer:
        """Generate a baseline answer using retrieved evidence."""

        result = self.query(question, top_k=top_k)

        if not result.evidence:
            raise ValueError(
                "No evidence was retrieved; answer generation skipped."
            )

        system_prompt = (
            "You are a retrieval-augmented question-answering assistant. "
            "Answer using only the supplied evidence. "
            "Do not invent facts or sources. "
            "If the evidence is insufficient, conflicting, or does not "
            "answer the question, clearly state that limitation."
        )

        prompt = (
            f"Question:\n{question}\n\n"
            f"Retrieved evidence:\n{result.context}\n\n"
            "Provide a clear answer grounded in the evidence. "
            "Mention important limitations where necessary."
        )

        response: LLMResponse = provider.generate(
            prompt,
            system=system_prompt,
            temperature=0.0,
            max_tokens=512,
        )

        return RAGAnswer(
            query=question,
            answer=response.text,
            provider=response.provider,
            evidence=result.evidence,
            context=result.context,
            fallback_used=response.fallback_used,
        )
