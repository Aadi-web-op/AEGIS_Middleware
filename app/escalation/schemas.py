from enum import Enum
from pydantic import BaseModel, Field


class EscalationStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EscalationCreateRequest(BaseModel):
    request_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    decision: str = "ESCALATE"
    query: str | None = None
    answer: str | None = None
    notes: str | None = None


class EscalationStatusUpdateRequest(BaseModel):
    status: EscalationStatus
    notes: str | None = None


class EscalationRecord(BaseModel):
    escalation_id: str
    request_id: str
    reason: str
    decision: str
    status: EscalationStatus
    query: str | None = None
    answer: str | None = None
    notes: str | None = None
    created_at: str
    updated_at: str
