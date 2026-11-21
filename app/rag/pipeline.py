from dataclasses import dataclass
from typing import List

from app.ingestion.chunker import DocumentChunk
from app.retrieval.vector_store import VectorStore


@dataclass
class RAGResult:
    query: str
    context: str
    evidence: List[DocumentChunk]


class RAGPipeline:
    """
    Retrieval layer for AEGIS RAG.

    This component retrieves relevant evidence and prepares
    the context for an LLM provider.

    It does NOT implement the LLM provider and does NOT
    make the final AEGIS decision.
    """

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ) -> RAGResult:
        results = self.vector_store.search(
            query=query,
            top_k=top_k,
        )

        evidence = [chunk for chunk, _score in results]

        context_parts = []

        for index, chunk in enumerate(evidence):
            context_parts.append(
                f"[Evidence {index}]\n"
                f"Source: {chunk.source}\n"
                f"Date: {chunk.date}\n"
                f"Version: {chunk.version}\n"
                f"Text: {chunk.text}"
            )

        context = "\n\n".join(context_parts)

        return RAGResult(
            query=query,
            context=context,
            evidence=evidence,
        )