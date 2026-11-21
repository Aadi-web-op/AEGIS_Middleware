import datetime
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Decision(str, Enum):
    ANSWER = "ANSWER"
    CAVEAT = "CAVEAT"
    ESCALATE = "ESCALATE"
    ABSTAIN = "ABSTAIN"


class RecommendedAction(str, Enum):
    RETURN_ANSWER = "return_answer"
    RETURN_WITH_CAVEAT = "return_with_caveat"
    ASK_CLARIFYING_QUESTION = "ask_clarifying_question"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    ABSTAIN = "abstain"


class ReasonCode(str, Enum):
    NO_EVIDENCE = "NO_EVIDENCE"
    LOW_RELEVANCE = "LOW_RELEVANCE"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    CONTRADICTION = "CONTRADICTION"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    AMBIGUOUS_QUERY = "AMBIGUOUS_QUERY"
    SIGNAL_UNAVAILABLE = "SIGNAL_UNAVAILABLE"


class ClaimStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


class EvidenceItem(BaseModel):
    text: str = Field(min_length=1)
    source: str | None = None
    date: datetime.date | None = None
    version: str | None = None
    document_content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class Reason(BaseModel):
    code: ReasonCode
    message: str


class SignalResult(BaseModel):
    """What every signal module returns. value=None means 'could not compute'."""
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    reasons: list[Reason] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class Signals(BaseModel):
    relevance: float | None = Field(default=None, ge=0.0, le=1.0)
    entailment: float | None = Field(default=None, ge=0.0, le=1.0)
    contradiction: float | None = Field(default=None, ge=0.0, le=1.0)
    freshness: float | None = Field(default=None, ge=0.0, le=1.0)
    completeness: float | None = Field(default=None, ge=0.0, le=1.0)
    ambiguity: float | None = Field(default=None, ge=0.0, le=1.0)


class ClaimResult(BaseModel):
    claim: str
    status: ClaimStatus
    support: float = Field(ge=0.0, le=1.0)
    evidence_indices: list[int] = Field(default_factory=list)
    # --- additive (finale contract, section 2) ---
    supporting_evidence_indices: list[int] = Field(default_factory=list)
    contradicting_evidence_indices: list[int] = Field(default_factory=list)
    # Why this claim got its status, in plain language.
    reason: str | None = None
    # [start, end) character offsets of the claim inside the request's
    # `answer` when it is a verbatim substring, else None.
    span: list[int] | None = None
    # Share of the claim's content words found in its best passage (0..1).
    # None when it was not measured.
    grounding: float | None = Field(default=None, ge=0.0, le=1.0)


class ExplanationFactor(BaseModel):
    """One measured value that pushed the decision, and how."""
    signal: str
    value: float | None = None
    threshold: float | None = None
    comparison: str | None = None  # "below" | "above" | "at_or_above" | "unavailable" | ...
    effect: Decision | None = None
    message: str


class Explanation(BaseModel):
    summary: str
    decisive_rule: str | None = None
    factors: list[ExplanationFactor] = Field(default_factory=list)


class EvaluateRequest(BaseModel):
    query: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    profile: str = "standard"
    time_sensitive: bool = True


class SignalChange(BaseModel):
    signal: str
    current: float
    target: float
    delta: float
    resulting_decision: Decision
    resulting_score: float
    hint: str


class PolicyExplanation(BaseModel):
    score_only_decision: Decision
    policy_reasons: list[Reason]
    contributions: dict[str, float]
    unavailable_signals: list[str]
    minimum_change: SignalChange | None = None


class HighlightSpan(BaseModel):
    """A sentence inside one evidence passage, tied to the claim it bears on."""
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    kind: str  # "support" | "conflict"
    claim_index: int
    overlap: float = Field(ge=0.0, le=1.0)


class NumberMark(BaseModel):
    """A number in the evidence that disagrees with the claim (12 vs 18)."""
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    value: str
    claim_value: str
    claim_index: int


class EvidenceHighlight(BaseModel):
    evidence_index: int
    source: str | None = None
    version: str | None = None
    text: str
    spans: list[HighlightSpan] = Field(default_factory=list)
    numbers: list[NumberMark] = Field(default_factory=list)


class EvaluateResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    decision: Decision
    answerability_score: float = Field(ge=0.0, le=1.0)
    signals: Signals
    reasons: list[Reason] = Field(default_factory=list)
    claims: list[ClaimResult] = Field(default_factory=list)
    caveat_text: str | None = None
    clarifying_question: str | None = None
    recommended_action: RecommendedAction
    degraded: bool = False
    policy_version: str = "0.1.0"
    latency_ms: float | None = None
    trace: dict[str, Any] | None = None
    # --- additive (finale contract, section 2); optional for old clients ---
    headline: str | None = None
    unavailable_signals: list[str] = Field(default_factory=list)
    explanation: Explanation | None = None
    # The answer text that was evaluated, when the server produced it (the
    # RAG workflow generates it). `claims[].span` offsets index into this
    # string. None for /v1/evaluate, where the caller supplied the answer.
    answer: str | None = None
    # Counterfactual for ESCALATE: smallest single-signal change that flips
    # the decision, computed by replaying the policy (app/core/explainer.py).
    counterfactual: PolicyExplanation | None = None
    # Sentence-level support/conflict spans per passage (app/evidence/highlight.py).
    highlights: list[EvidenceHighlight] = Field(default_factory=list)
