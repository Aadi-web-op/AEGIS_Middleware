"""Shared content identities for evidence and document revisions."""

from hashlib import sha256
from unicodedata import normalize


def normalized_text(text: str) -> str:
    return " ".join(normalize("NFC", text).split())


def content_hash(text: str) -> str:
    return sha256(normalized_text(text).encode("utf-8")).hexdigest()


def document_id(
    source: str | None, version: str | None, revision_hash: str | None = None
) -> str | None:
    if not source:
        return None
    if revision_hash:
        # Frame the metadata so names/versions containing delimiters cannot collide.
        identity = f"{len(source)}:{source}{len(version or '')}:{version or ''}{revision_hash}"
        return f"doc:sha256:{sha256(identity.encode('utf-8')).hexdigest()}"
    return f"doc:{source}@{version}" if version else f"doc:{source}"
