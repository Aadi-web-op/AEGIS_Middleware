from dataclasses import dataclass
from typing import List


@dataclass
class DocumentChunk:
    text: str
    source: str
    date: str | None = None
    version: str | None = None
    chunk_id: int = 0


def chunk_text(
    text: str,
    source: str,
    chunk_size: int = 500,
    overlap: int = 50,
    date: str | None = None,
    version: str | None = None,
) -> List[DocumentChunk]:
    """
    Split document text into overlapping chunks.
    """

    if not text.strip():
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    words = text.split()
    chunks = []

    start = 0
    chunk_id = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))

        chunk = " ".join(words[start:end])

        chunks.append(
            DocumentChunk(
                text=chunk,
                source=source,
                date=date,
                version=version,
                chunk_id=chunk_id,
            )
        )

        chunk_id += 1

        if end == len(words):
            break

        start = end - overlap

    return chunks