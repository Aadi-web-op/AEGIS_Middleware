import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.audit.logger import sanitize_secrets
from app.escalation.schemas import (
    EscalationRecord,
    EscalationStatus,
)

logger = logging.getLogger(__name__)


class EscalationError(Exception):
    """Base exception for escalation queue errors."""


class EscalationNotFoundError(EscalationError):
    """Raised when an escalation ID is not found."""


class DuplicateEscalationError(EscalationError):
    """Raised when an active escalation already exists for a request_id."""


class InvalidStatusTransitionError(EscalationError):
    """Raised when attempting an invalid status transition."""


VALID_TRANSITIONS = {
    EscalationStatus.PENDING: {
        EscalationStatus.IN_REVIEW,
        EscalationStatus.RESOLVED,
        EscalationStatus.DISMISSED,
    },
    EscalationStatus.IN_REVIEW: {
        EscalationStatus.PENDING,
        EscalationStatus.RESOLVED,
        EscalationStatus.DISMISSED,
    },
    EscalationStatus.RESOLVED: set(),
    EscalationStatus.DISMISSED: set(),
}


def default_escalations_db_path() -> Path:
    override = os.environ.get("AEGIS_ESCALATIONS_DB_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "escalations.db"


class EscalationQueue:
    """SQLite-backed queue for persisting and managing human escalation records."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path) if db_path else str(default_escalations_db_path())
        self._is_memory = self.db_path == ":memory:" or "mode=memory" in self.db_path

        if self._is_memory:
            self._shared_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        else:
            self._shared_conn = None
            parent = Path(self.db_path).parent
            if parent and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        sql = """
            CREATE TABLE IF NOT EXISTS escalations (
                escalation_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                decision TEXT NOT NULL,
                status TEXT NOT NULL,
                query TEXT,
                answer TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_escalation_status ON escalations(status);
            CREATE INDEX IF NOT EXISTS idx_escalation_request_id ON escalations(request_id);
        """
        if self._is_memory:
            with self._shared_conn:
                self._shared_conn.executescript(sql)
        else:
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(sql)

    def _get_connection(self):
        return self._shared_conn if self._is_memory else sqlite3.connect(self.db_path)

    def enqueue(
        self,
        request_id: str,
        reason: str,
        decision: str = "ESCALATE",
        query: str | None = None,
        answer: str | None = None,
        notes: str | None = None,
        raise_on_duplicate: bool = False,
    ) -> EscalationRecord:
        """Enqueue an escalation record. Idempotent if raise_on_duplicate is False."""
        existing = self.get_by_request_id(request_id)
        if existing is not None:
            if existing.status in (EscalationStatus.PENDING, EscalationStatus.IN_REVIEW):
                if raise_on_duplicate:
                    raise DuplicateEscalationError(
                        f"Active escalation already exists for request_id: {request_id}"
                    )
                return existing

        now = datetime.now(timezone.utc).isoformat()
        escalation_id = f"esc-{uuid.uuid4().hex[:12]}"
        record = EscalationRecord(
            escalation_id=escalation_id,
            request_id=request_id,
            reason=sanitize_secrets(reason) or "",
            decision=decision,
            status=EscalationStatus.PENDING,
            query=sanitize_secrets(query),
            answer=sanitize_secrets(answer),
            notes=sanitize_secrets(notes),
            created_at=now,
            updated_at=now,
        )

        sql = """
            INSERT INTO escalations (
                escalation_id, request_id, reason, decision, status,
                query, answer, notes, created_at, updated_at
            ) VALUES (
                :escalation_id, :request_id, :reason, :decision, :status,
                :query, :answer, :notes, :created_at, :updated_at
            )
        """
        params = record.model_dump()
        params["status"] = record.status.value

        conn = self._get_connection()
        try:
            if self._is_memory:
                with conn:
                    conn.execute(sql, params)
            else:
                with conn:
                    conn.execute(sql, params)
        finally:
            if not self._is_memory:
                conn.close()

        return record

    def get_by_id(self, escalation_id: str) -> EscalationRecord:
        """Retrieve an escalation by ID. Raises EscalationNotFoundError if missing."""
        sql = "SELECT * FROM escalations WHERE escalation_id = ?"
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, (escalation_id,))
            row = cursor.fetchone()
            if row is None:
                raise EscalationNotFoundError(f"Escalation not found: {escalation_id}")
            return EscalationRecord(**dict(row))
        finally:
            if not self._is_memory:
                conn.close()

    def get_by_request_id(self, request_id: str) -> EscalationRecord | None:
        """Find the latest escalation record for a given request_id."""
        sql = "SELECT * FROM escalations WHERE request_id = ? ORDER BY created_at DESC LIMIT 1"
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, (request_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return EscalationRecord(**dict(row))
        finally:
            if not self._is_memory:
                conn.close()

    def list_escalations(
        self,
        status: EscalationStatus | str | None = None,
        request_id: str | None = None,
        limit: int = 50,
    ) -> list[EscalationRecord]:
        """List escalations, optionally filtered by status and/or request_id."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            conditions = []
            params = []
            if status is not None:
                status_val = status.value if isinstance(status, EscalationStatus) else str(status)
                conditions.append("status = ?")
                params.append(status_val)
            if request_id is not None:
                conditions.append("request_id = ?")
                params.append(request_id)

            sql = "SELECT * FROM escalations"
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return [EscalationRecord(**dict(r)) for r in rows]
        finally:
            if not self._is_memory:
                conn.close()

    def update_status(
        self,
        escalation_id: str,
        new_status: EscalationStatus | str,
        notes: str | None = None,
    ) -> EscalationRecord:
        """Update escalation status with strict transition validation."""
        current = self.get_by_id(escalation_id)

        try:
            target_status = (
                new_status
                if isinstance(new_status, EscalationStatus)
                else EscalationStatus(new_status)
            )
        except ValueError as exc:
            raise InvalidStatusTransitionError(f"Invalid status: {new_status}") from exc

        # If status is changing, validate transition
        if target_status != current.status:
            allowed = VALID_TRANSITIONS.get(current.status, set())
            if target_status not in allowed:
                raise InvalidStatusTransitionError(
                    f"Cannot transition escalation from {current.status.value} to {target_status.value}"
                )

        now = datetime.now(timezone.utc).isoformat()
        updated_notes = sanitize_secrets(notes) if notes is not None else current.notes

        sql = """
            UPDATE escalations
            SET status = ?, notes = ?, updated_at = ?
            WHERE escalation_id = ?
        """
        conn = self._get_connection()
        try:
            if self._is_memory:
                with conn:
                    conn.execute(sql, (target_status.value, updated_notes, now, escalation_id))
            else:
                with conn:
                    conn.execute(sql, (target_status.value, updated_notes, now, escalation_id))
        finally:
            if not self._is_memory:
                conn.close()

        return self.get_by_id(escalation_id)

    def close(self) -> None:
        if self._is_memory and self._shared_conn:
            self._shared_conn.close()
            self._shared_conn = None
