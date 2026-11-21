"""Completeness Signal - Determines whether evidence covers all parts of the query.

Approach (deliberately simple and robust):
  1. Decompose the query into aspects (sub-questions) by splitting on
     conjunctions and list punctuation.
  2. Embed each aspect and each evidence passage once.
  3. An aspect is "covered" if at least one evidence passage is
     semantically close to it.
  4. completeness = covered_aspects / total_aspects.

The signal is conservative: no evidence -> 0.0, and an aspect is only
counted as covered when similarity clears a threshold.
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import torch
from torch.nn.functional import cosine_similarity

from aegis_core.signals.base import BaseSignal, SignalResult, SignalName
from aegis_core.models.registry import model_registry, ModelConfig, EMBEDDING_CANDIDATES

logger = logging.getLogger(__name__)

# Conjunctions / list markers that split a multi-part question.
_SPLIT_WORDS = [
    "and", "or", "also", "plus", "as well as", "as well",
    "along with", "in addition to", "while", "whereas", "whether",
]
_SPLIT_RE = re.compile(
    r"(?:\b(?:%s)\b|;|\n)" % "|".join(re.escape(w) for w in _SPLIT_WORDS),
    re.IGNORECASE,
)

_INTERROGATIVES = ("what", "which", "how", "why", "when", "where", "who", "whom", "whose", "does", "do", "is", "are", "can", "could", "will", "would", "should")


def decompose_query(query: str, max_aspects: int = 6) -> List[str]:
    """
    Split a query into aspect fragments.

    Keeps the interrogative stem with each fragment so that an aspect like
    "does it apply to contractors" stays a meaningful question.
    """
    if not query or not query.strip():
        return []

    q = query.strip().rstrip("?").strip()

    # Split on conjunctions and list punctuation.
    parts = [p.strip(" ,.-") for p in _SPLIT_RE.split(q)]
    parts = [p for p in parts if len(p) > 2]

    # If splitting produced nothing useful, treat the whole query as one aspect.
    if not parts:
        return [q]

    # Attach the leading interrogative stem to the first fragment when the
    # fragment lost it (e.g. "refund period and does it apply to contractors").
    aspects: List[str] = []
    stem = ""
    first_word = parts[0].split()[0].lower() if parts[0].split() else ""
    if first_word in _INTERROGATIVES:
        stem = parts[0].split()[0]

    for i, part in enumerate(parts[:max_aspects]):
        words = part.split()
        if not words:
            continue
        # If fragment doesn't start with an interrogative and we have a stem,
        # prepend it so similarity checks against evidence are meaningful.
        if i > 0 and words[0].lower() not in _INTERROGATIVES and stem:
            part = f"{stem} {part}"
        aspects.append(part.strip())

    return aspects or [q]


class CompletenessSignal(BaseSignal):
    """Evidence coverage signal over query aspects."""

    def __init__(
        self,
        embedding_config: Optional[ModelConfig] = None,
        coverage_threshold: float = 0.35,
        max_aspects: int = 6,
        max_evidence: int = 8,
    ):
        self.embedding_config = embedding_config or EMBEDDING_CANDIDATES[0]
        self.coverage_threshold = coverage_threshold
        self.max_aspects = max_aspects
        self.max_evidence = max_evidence
        self._embedding_model = None

    @property
    def signal_name(self) -> SignalName:
        return SignalName.COMPLETENESS

    @property
    def embedding_model(self):
        if self._embedding_model is None:
            self._embedding_model = model_registry.get_embedding_model(self.embedding_config)
        return self._embedding_model

    def evaluate(
        self,
        query: str,
        answer: str,
        evidence: List[str],
        **kwargs
    ) -> SignalResult:
        """
        Evaluate whether the evidence covers all important parts of the query.

        Returns completeness in [0, 1] plus covered/missing aspect lists.
        """
        if not query or not query.strip():
            return SignalResult(
                signal=SignalName.COMPLETENESS,
                value=0.0,
                reasons=["Empty query; cannot determine required information"],
                details={"aspects": [], "covered": [], "missing": []},
            )

        if not evidence:
            return SignalResult(
                signal=SignalName.COMPLETENESS,
                value=0.0,
                reasons=["No evidence provided; cannot confirm coverage of the query"],
                details={
                    "completeness_score": 0.0,
                    "aspects": [],
                    "covered_aspects": [],
                    "missing_aspects": [],
                    "covered_count": 0,
                    "total_aspects": 0,
                    "coverage_threshold": self.coverage_threshold,
                    "evidence_count": 0,
                },
            )

        aspects = decompose_query(query, self.max_aspects)
        evidence = evidence[: self.max_evidence]

        # Embed aspects and evidence in one batched call each.
        try:
            aspect_embs = self.embedding_model.encode(
                aspects, convert_to_tensor=True, show_progress_bar=False
            )
            evidence_embs = self.embedding_model.encode(
                evidence, convert_to_tensor=True, show_progress_bar=False
            )
        except Exception as exc:
            logger.error("Embedding failed in completeness: %s", exc)
            return SignalResult(
                signal=SignalName.COMPLETENESS,
                value=0.0,
                reasons=[f"Embedding computation failed: {exc}"],
                details={"error": str(exc)},
            )

        # Similarity matrix [aspects x evidence].
        sims = cosine_similarity(aspect_embs, evidence_embs).cpu().numpy()

        covered: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []
        for i, aspect in enumerate(aspects):
            row = sims[i]
            best = float(row.max()) if row.size else 0.0
            best_idx = int(row.argmax()) if row.size else -1
            entry = {
                "aspect": aspect,
                "best_similarity": round(best, 4),
                "best_evidence": evidence[best_idx] if 0 <= best_idx < len(evidence) else None,
            }
            if best >= self.coverage_threshold:
                covered.append(entry)
            else:
                missing.append(entry)

        total = len(aspects)
        completeness = round(len(covered) / total, 4) if total else (1.0 if evidence else 0.0)

        reasons = self._generate_reasons(completeness, covered, missing, total)

        return SignalResult(
            signal=SignalName.COMPLETENESS,
            value=completeness,
            reasons=reasons,
            details={
                "completeness_score": completeness,
                "aspects": aspects,
                "covered_aspects": [c["aspect"] for c in covered],
                "missing_aspects": [m["aspect"] for m in missing],
                "covered_details": covered,
                "missing_details": missing,
                "covered_count": len(covered),
                "total_aspects": total,
                "coverage_threshold": self.coverage_threshold,
                "evidence_count": len(evidence),
                "similarity_matrix": sims.tolist(),
                "embedding_model": self.embedding_config.name,
            },
        )

    def _generate_reasons(
        self,
        completeness: float,
        covered: List[Dict[str, Any]],
        missing: List[Dict[str, Any]],
        total: int,
    ) -> List[str]:
        reasons: List[str] = []

        if not total:
            return reasons

        if completeness >= 1.0:
            reasons.append(f"Evidence covers all {total} aspect(s) of the query")
        elif completeness >= 0.6:
            reasons.append(
                f"Evidence covers {len(covered)}/{total} aspects of the query"
            )
        elif completeness >= 0.3:
            reasons.append(
                f"Evidence partially covers the query ({len(covered)}/{total} aspects)"
            )
        else:
            reasons.append(
                f"Evidence covers only {len(covered)}/{total} aspects of the query"
            )

        for m in missing[:3]:
            reasons.append(f"Missing information about: \"{m['aspect']}\"")

        return reasons


def create_completeness_signal(**kwargs) -> CompletenessSignal:
    return CompletenessSignal(**kwargs)
