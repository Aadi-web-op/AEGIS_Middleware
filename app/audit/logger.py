import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.schemas import EvaluateRequest, EvaluateResponse

logger = logging.getLogger(__name__)

SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"gsk_[A-Za-z0-9]+", re.IGNORECASE),
    re.compile(
        r"(?:api_key|apikey|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]+['\"]?",
        re.IGNORECASE,
    ),
]


def default_audit_db_path() -> Path:
    override = os.environ.get("AEGIS_AUDIT_DB_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "audit.db"


def sanitize_secrets(text: str | None) -> str | None:
    """Ensure no API keys, Bearer tokens, or environment secrets are persisted."""
    if not text:
        return text

    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)

    # Scrub exact values of any sensitive environment variables
    for key, val in os.environ.items():
        if any(term in key.upper() for term in ("KEY", "SECRET", "TOKEN", "AUTH")):
            clean_val = val.strip().strip('"').strip("'")
            if len(clean_val) >= 6 and clean_val in sanitized:
                sanitized = sanitized.replace(clean_val, "[REDACTED]")

    return sanitized


class AuditLogger:
    """Persists AEGIS evaluation requests and outcomes in SQLite."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path) if db_path else str(default_audit_db_path())
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
            CREATE TABLE IF NOT EXISTS audit_logs (
                request_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                query TEXT,
                answer TEXT,
                profile TEXT,
                decision TEXT,
                answerability_score REAL,
                signals TEXT,
                reason_codes TEXT,
                generation_success INTEGER,
                error_message TEXT,
                latency_ms REAL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_decision ON audit_logs(decision);
        """
        if self._is_memory:
            with self._shared_conn:
                self._shared_conn.executescript(sql)
        else:
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(sql)

    def log_evaluation(
        self,
        request: EvaluateRequest,
        response: EvaluateResponse,
        generation_success: bool | None = None,
    ) -> str | None:
        """Persist evaluation request and response details."""
        try:
            req_id = response.request_id or uuid.uuid4().hex
            timestamp = datetime.now(timezone.utc).isoformat()
            decision = (
                response.decision.value
                if hasattr(response.decision, "value")
                else str(response.decision)
            )

            signals_dict = None
            if response.signals:
                signals_dict = response.signals.model_dump(exclude_none=True)

            reason_codes = None
            if response.reasons:
                reason_codes = [
                    r.code.value if hasattr(r.code, "value") else str(r.code)
                    for r in response.reasons
                ]

            query = sanitize_secrets(request.query)
            answer = sanitize_secrets(request.answer)

            record = {
                "request_id": req_id,
                "timestamp": timestamp,
                "query": query,
                "answer": answer,
                "profile": request.profile,
                "decision": decision,
                "answerability_score": response.answerability_score,
                "signals": json.dumps(signals_dict) if signals_dict is not None else None,
                "reason_codes": json.dumps(reason_codes) if reason_codes is not None else None,
                "generation_success": (
                    1 if generation_success is True else (0 if generation_success is False else None)
                ),
                "error_message": None,
                "latency_ms": response.latency_ms,
            }

            self._insert_record(record)
            return req_id
        except Exception as exc:
            logger.warning("Failed to record evaluation in audit log: %s", exc)
            return None

    def log_generation_failure(
        self,
        query: str,
        error: str,
        request_id: str | None = None,
        profile: str = "standard",
    ) -> str | None:
        """Persist request and error details when LLM answer generation fails."""
        try:
            req_id = request_id or uuid.uuid4().hex
            timestamp = datetime.now(timezone.utc).isoformat()
            sanitized_query = sanitize_secrets(query)
            sanitized_error = sanitize_secrets(error)

            record = {
                "request_id": req_id,
                "timestamp": timestamp,
                "query": sanitized_query,
                "answer": None,
                "profile": profile,
                "decision": None,
                "answerability_score": None,
                "signals": None,
                "reason_codes": None,
                "generation_success": 0,
                "error_message": sanitized_error,
                "latency_ms": None,
            }

            self._insert_record(record)
            return req_id
        except Exception as exc:
            logger.warning("Failed to record generation failure in audit log: %s", exc)
            return None

    def _insert_record(self, record: dict) -> None:
        sql = """
            INSERT OR REPLACE INTO audit_logs (
                request_id, timestamp, query, answer, profile, decision,
                answerability_score, signals, reason_codes, generation_success,
                error_message, latency_ms
            ) VALUES (
                :request_id, :timestamp, :query, :answer, :profile, :decision,
                :answerability_score, :signals, :reason_codes, :generation_success,
                :error_message, :latency_ms
            )
        """
        if self._is_memory:
            with self._shared_conn:
                self._shared_conn.execute(sql, record)
        else:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(sql, record)

    def get_record(self, request_id: str) -> dict | None:
        try:
            conn = self._shared_conn if self._is_memory else sqlite3.connect(self.db_path)
            if conn is None:
                return None
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM audit_logs WHERE request_id = ?", (request_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                res = dict(row)
                if res.get("signals"):
                    try:
                        res["signals"] = json.loads(res["signals"])
                    except Exception:
                        pass
                if res.get("reason_codes"):
                    try:
                        res["reason_codes"] = json.loads(res["reason_codes"])
                    except Exception:
                        pass
                return res
            finally:
                if not self._is_memory and conn is not None:
                    conn.close()
        except Exception as exc:
            logger.warning("Failed to retrieve record from audit log: %s", exc)
            return None

    def list_records(self, limit: int = 50) -> list[dict]:
        try:
            conn = self._shared_conn if self._is_memory else sqlite3.connect(self.db_path)
            if conn is None:
                return []
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    res = dict(row)
                    if res.get("signals"):
                        try:
                            res["signals"] = json.loads(res["signals"])
                        except Exception:
                            pass
                    if res.get("reason_codes"):
                        try:
                            res["reason_codes"] = json.loads(res["reason_codes"])
                        except Exception:
                            pass
                    results.append(res)
                return results
            finally:
                if not self._is_memory and conn is not None:
                    conn.close()
        except Exception as exc:
            logger.warning("Failed to list records from audit log: %s", exc)
            return []

    def close(self) -> None:
        if self._is_memory and self._shared_conn:
            self._shared_conn.close()
            self._shared_conn = None
