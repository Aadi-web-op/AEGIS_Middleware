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

class EvaluateRequest(BaseModel):
    query: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    profile: str = "standard"
    time_sensitive: bool = True




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
    