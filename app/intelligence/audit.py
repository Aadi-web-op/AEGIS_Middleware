"""Read-only views of the SQLite audit log (the system of record).

Decision/reason distributions and trends come from here, so they work
whether or not Neo4j is running. Timestamps are the real ones written by
`AuditLogger`; nothing is synthesised.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any, Dict, List, Optional

from app.audit import default_audit_db_path


class AuditUnavailable(RuntimeError):
    """The audit database could not be read."""


class AuditReader:
    """Reads `audit_logs` through an AuditLogger (shares an in-memory
    connection when there is one) or straight from a database path."""

    def __init__(self, audit_logger: Any = None, db_path: Optional[str] = None):
        self._logger = audit_logger
        self._db_path = db_path

    def _rows(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        shared = getattr(self._logger, "_shared_conn", None)
        try:
            if shared is not None:
                cur = shared.execute(sql, params)
                names = [c[0] for c in cur.description]
                return [dict(zip(names, row)) for row in cur.fetchall()]
            path = (
                self._db_path
                or getattr(self._logger, "db_path", None)
                or str(default_audit_db_path())
            )
            conn = sqlite3.connect(path)
            try:
                cur = conn.execute(sql, params)
                names = [c[0] for c in cur.description]
                return [dict(zip(names, row)) for row in cur.fetchall()]
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return []  # a fresh database simply has no decisions yet
            raise AuditUnavailable(str(exc)) from exc
        except sqlite3.Error as exc:
            raise AuditUnavailable(str(exc)) from exc

    @staticmethod
    def _like(prefix: str) -> str:
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return escaped + "%"

    def decision_distribution(self, prefix: str = "") -> Dict[str, int]:
        rows = self._rows(
            "SELECT decision, COUNT(*) AS n FROM audit_logs "
            "WHERE decision IS NOT NULL AND request_id LIKE ? ESCAPE '\\' "
            "GROUP BY decision",
            (self._like(prefix),),
        )
        return {r["decision"]: int(r["n"]) for r in rows}

    def reason_distribution(self, prefix: str = "") -> Dict[str, int]:
        rows = self._rows(
            "SELECT reason_codes FROM audit_logs "
            "WHERE decision IS NOT NULL AND reason_codes IS NOT NULL "
            "AND request_id LIKE ? ESCAPE '\\'",
            (self._like(prefix),),
        )
        counts: Counter = Counter()
        for row in rows:
            try:
                codes = json.loads(row["reason_codes"] or "[]")
            except (ValueError, TypeError):
                continue
            # A code is counted once per decision, however often it repeats.
            for code in set(c for c in codes if isinstance(c, str)):
                counts[code] += 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def trends(self, bucket: str = "day", prefix: str = "") -> List[Dict[str, Any]]:
        width = 13 if bucket == "hour" else 10
        rows = self._rows(
            "SELECT substr(timestamp, 1, ?) AS bucket, decision, COUNT(*) AS n "
            "FROM audit_logs WHERE decision IS NOT NULL "
            "AND request_id LIKE ? ESCAPE '\\' "
            "GROUP BY bucket, decision ORDER BY bucket",
            (width, self._like(prefix)),
        )
        buckets: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            item = buckets.setdefault(
                row["bucket"],
                {"bucket": row["bucket"], "total": 0,
                 "ANSWER": 0, "CAVEAT": 0, "ESCALATE": 0, "ABSTAIN": 0},
            )
            item[row["decision"]] = item.get(row["decision"], 0) + int(row["n"])
            item["total"] += int(row["n"])
        return [buckets[k] for k in sorted(buckets)]

    def queries_by_request_id(self, request_ids: List[str]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        ids = list(dict.fromkeys(request_ids))
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for row in self._rows(
                f"SELECT request_id, query FROM audit_logs WHERE request_id IN ({marks})",
                tuple(chunk),
            ):
                if row.get("query"):
                    out[row["request_id"]] = row["query"]
        return out
