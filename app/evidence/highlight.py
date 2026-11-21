"""Sentence-level evidence highlighting (finale feature 2).

Given an evaluated request, point at the exact sentence in each passage that
supports or contradicts each claim, and mark numbers that disagree with the
claim (e.g. "12 days" in the policy vs "18 days" in the answer).

Additive by design: it reads the claims the evaluator already produced
(`supporting_evidence_indices` / `contradicting_evidence_indices`, decided by
NLI) and only *locates* the sentence inside the passage. Locating is lexical
(content-word overlap, numeric conflicts break ties), so it is deterministic,
adds no model calls and cannot change a decision.
"""

from __future__ import annotations

import re
from typing import Iterable

from aegis_core.utils.claim_split import content_tokens
from aegis_core.utils.numeric_date import compare_quantities, extract_quantities
from app.schemas import (
    EvaluateRequest,
    EvaluateResponse,
    EvidenceHighlight,
    HighlightSpan,
    NumberMark,
)

# A sentence ends at . ! ? (or a newline) followed by whitespace. Decimal
# points ("2.5 days") are not followed by whitespace, so they do not split.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Character ranges [start, end) of the non-empty sentences in `text`."""
    ranges: list[tuple[int, int]] = []
    position = 0
    for match in _SENTENCE_END.finditer(text):
        ranges.append((position, match.start()))
        position = match.end()
    ranges.append((position, len(text)))
    out = []
    for start, end in ranges:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            out.append((start, end))
    return out


def _numeric_conflicts(claim: str, sentence: str, offset: int) -> list[tuple[int, int, str, str]]:
    marks = []
    claim_quantities = extract_quantities(claim)
    for evidence_quantity in extract_quantities(sentence):
        for claim_quantity in claim_quantities:
            if compare_quantities(claim_quantity, evidence_quantity):
                marks.append((
                    offset + evidence_quantity.start,
                    offset + evidence_quantity.end,
                    evidence_quantity.text,
                    claim_quantity.text,
                ))
                break
    return marks


def _best_sentence(
    claim: str, text: str, sentences: list[tuple[int, int]], prefer_conflict: bool
) -> tuple[int, int, float] | None:
    tokens = content_tokens(claim)
    best: tuple[float, int, int, float] | None = None
    for start, end in sentences:
        sentence = text[start:end]
        overlap = len(tokens & content_tokens(sentence)) / len(tokens) if tokens else 0.0
        rank = overlap
        if prefer_conflict and _numeric_conflicts(claim, sentence, start):
            rank += 1.0  # a sentence that disagrees on a number is the one to show
        if best is None or rank > best[0]:
            best = (rank, start, end, overlap)
    if best is None:
        return None
    return best[1], best[2], round(best[3], 4)


def _indices(values: Iterable[int] | None, size: int) -> list[int]:
    return sorted({i for i in (values or []) if isinstance(i, int) and 0 <= i < size})


def build_highlights(
    request: EvaluateRequest, response: EvaluateResponse
) -> list[EvidenceHighlight]:
    passages = [item.text or "" for item in request.evidence]
    sentence_cache: dict[int, list[tuple[int, int]]] = {}
    spans: dict[int, list[HighlightSpan]] = {}
    numbers: dict[int, list[NumberMark]] = {}

    for claim_index, claim in enumerate(response.claims):
        for kind, indices in (
            ("conflict", claim.contradicting_evidence_indices),
            ("support", claim.supporting_evidence_indices),
        ):
            for evidence_index in _indices(indices, len(passages)):
                text = passages[evidence_index]
                sentences = sentence_cache.setdefault(evidence_index, split_sentences(text))
                found = _best_sentence(claim.claim, text, sentences, kind == "conflict")
                if found is None:
                    continue
                start, end, overlap = found
                spans.setdefault(evidence_index, []).append(HighlightSpan(
                    start=start, end=end, kind=kind, claim_index=claim_index, overlap=overlap,
                ))
                if kind == "conflict":
                    for n_start, n_end, value, claim_value in _numeric_conflicts(
                        claim.claim, text[start:end], start
                    ):
                        numbers.setdefault(evidence_index, []).append(NumberMark(
                            start=n_start, end=n_end, value=value,
                            claim_value=claim_value, claim_index=claim_index,
                        ))

    highlights = []
    for evidence_index in sorted(set(spans) | set(numbers)):
        item = request.evidence[evidence_index]
        highlights.append(EvidenceHighlight(
            evidence_index=evidence_index,
            source=item.source,
            version=item.version,
            text=passages[evidence_index],
            spans=sorted(spans.get(evidence_index, []), key=lambda s: (s.start, s.kind)),
            numbers=sorted(numbers.get(evidence_index, []), key=lambda n: n.start),
        ))
    return highlights
