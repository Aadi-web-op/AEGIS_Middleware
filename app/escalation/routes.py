from fastapi import APIRouter, HTTPException, Query, Request, status

from app.escalation.queue import (
    DuplicateEscalationError,
    EscalationNotFoundError,
    EscalationQueue,
    InvalidStatusTransitionError,
)
from app.escalation.schemas import (
    EscalationCreateRequest,
    EscalationRecord,
    EscalationStatus,
    EscalationStatusUpdateRequest,
)

router = APIRouter(prefix="/v1/escalations", tags=["Escalations"])


def _get_queue(request: Request) -> EscalationQueue:
    queue = getattr(request.app.state, "escalation_queue", None)
    if queue is None:
        queue = EscalationQueue()
        request.app.state.escalation_queue = queue
    return queue


@router.post("", response_model=EscalationRecord, status_code=status.HTTP_201_CREATED)
def create_escalation(payload: EscalationCreateRequest, request: Request):
    """Enqueue an escalation for human review."""
    queue = _get_queue(request)
    try:
        return queue.enqueue(
            request_id=payload.request_id,
            reason=payload.reason,
            decision=payload.decision,
            query=payload.query,
            answer=payload.answer,
            notes=payload.notes,
            raise_on_duplicate=True,
        )
    except DuplicateEscalationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get("", response_model=list[EscalationRecord])
def list_escalations(
    request: Request,
    status: EscalationStatus | None = Query(None, description="Filter by status (pending, in_review, resolved, dismissed)"),
    request_id: str | None = Query(None, description="Filter by request ID"),
    limit: int = Query(50, ge=1, le=500),
):
    """List escalations, optionally filtered by status and/or request_id."""
    queue = _get_queue(request)
    return queue.list_escalations(status=status, request_id=request_id, limit=limit)


@router.get("/pending", response_model=list[EscalationRecord])
def list_pending_escalations(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
):
    """List pending escalations awaiting human review."""
    queue = _get_queue(request)
    return queue.list_escalations(status=EscalationStatus.PENDING, limit=limit)


@router.get("/{escalation_id}", response_model=EscalationRecord)
def get_escalation(escalation_id: str, request: Request):
    """Retrieve an escalation record by its ID."""
    queue = _get_queue(request)
    try:
        return queue.get_by_id(escalation_id)
    except EscalationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch("/{escalation_id}", response_model=EscalationRecord)
@router.put("/{escalation_id}", response_model=EscalationRecord)
def update_escalation_status(
    escalation_id: str,
    payload: EscalationStatusUpdateRequest,
    request: Request,
):
    """Update escalation status (validating state transition) and reviewer notes."""
    queue = _get_queue(request)
    try:
        return queue.update_status(
            escalation_id=escalation_id,
            new_status=payload.status,
            notes=payload.notes,
        )
    except EscalationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvalidStatusTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
