"""Response models for /v1/intelligence (CONTRACTS.md section 5)."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

FindingKind = Literal[
    "unsupported_source",
    "contradiction_hotspot",
    "stale_version_in_use",
    "knowledge_gap",
    "escalation_root_cause",
    "uncertainty_source",
]


class Metric(BaseModel):
    name: str
    value: float
    numerator: int
    denominator: int


class Subject(BaseModel):
    type: str  # Document | Topic | ReasonCode | DocumentPair
    id: str


class Finding(BaseModel):
    id: str
    kind: FindingKind
    severity: Literal["high", "medium", "low"]
    title: str
    explanation: str
    metric: Metric
    subjects: List[Subject]
    request_ids: List[str]
    query: str
    # Additive: how the subject is linked to the failure ("direct" edges in
    # the graph, or only "considered" = retrieved in failing decisions).
    attribution: Literal["direct", "considered"] = "direct"
    details: Dict[str, Any] = Field(default_factory=dict)


class Exclusion(BaseModel):
    """Decisions a rule skipped because a field it needs is missing."""
    rule: str
    count: int
    reason: str


def finding_id(kind: str, *subject_ids: str) -> str:
    """Stable id: same kind + subjects -> same id across requests."""
    raw = kind + "|" + "|".join(sorted(subject_ids))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
