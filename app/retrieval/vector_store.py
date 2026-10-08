from typing import List

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from app.ingestion.chunker import DocumentChunk


class VectorStore:
    """
    FAISS-based vector store for document chunks.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        self.model = SentenceTransformer(model_name)
        self.chunks: List[DocumentChunk] = []

        # Determine embedding dimension from the model.
        dimension = self.model.get_sentence_embedding_dimension()

        if dimension is None:
            raise RuntimeError("Could not determine embedding dimension.")

        # Inner product works well with normalized embeddings.
        self.index = faiss.IndexFlatIP(dimension)

    def add_chunks(self, chunks: List[DocumentChunk]) -> None:
        """
        Generate embeddings for chunks and add them to FAISS.
        """

        if not chunks:
            return

        texts = [chunk.text for chunk in chunks]

        embeddings = self.model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype("float32")

        self.index.add(embeddings)
        self.chunks.extend(chunks)

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[tuple[DocumentChunk, float]]:
        """
        Retrieve the most relevant chunks for a query.
        """

        if not query.strip():
            return []

        if self.index.ntotal == 0:
            return []

        query_embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype("float32")

        scores, indices = self.index.search(
            query_embedding,
            min(top_k, self.index.ntotal),
        )

        results = []

        for score, index in zip(scores[0], indices[0]):
            if index == -1:
                continue

            results.append(
                (self.chunks[index], float(score))
            )

        return results