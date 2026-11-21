"""Fakes for intelligence tests.

`FakeReadDriver` mimics what `app.intelligence.queries.run` uses --
`driver.session(**kw)` as a context manager, `session.execute_read(fn)`
and `tx.run(cypher, params)` -- and answers each *named* query in
`QUERIES` from canned rows. Like a real managed transaction, `tx.run`
rejects anything but a plain string, which pins the regression where a
`neo4j.Query` object was passed inside `execute_read`.

(Modelled on tests/graph/fake_driver.py, which only covers writes.)
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.intelligence.queries import QUERIES

_NAME_BY_CYPHER = {cypher: name for name, cypher in QUERIES.items()}


class FakeRecord:
    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def data(self) -> Dict[str, Any]:
        return dict(self._data)


class FakeReadTx:
    def __init__(self, driver: "FakeReadDriver"):
        self._driver = driver

    def run(self, cypher: Any, parameters: Optional[Dict[str, Any]] = None, **kw: Any):
        if not isinstance(cypher, str):
            # The real ManagedTransaction.run raises TypeError for Query objects.
            raise TypeError("Query object is only supported for session.run")
        params = dict(parameters or {}, **kw)
        name = _NAME_BY_CYPHER.get(cypher)
        if name is None:
            raise AssertionError("unknown cypher (not a named query)")
        self._driver.calls.append((name, params))
        if self._driver.fail_on is not None and self._driver.fail_on(name):
            raise self._driver.error
        rows = self._driver.rows.get(name, [])
        if callable(rows):
            rows = rows(params)
        return [FakeRecord(r) for r in rows]


class FakeReadSession:
    def __init__(self, driver: "FakeReadDriver", database: Optional[str] = None):
        self._driver = driver
        self.database = database

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute_read(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self._driver.session_error is not None:
            raise self._driver.session_error
        return fn(FakeReadTx(self._driver), *args, **kwargs)


class FakeReadDriver:
    def __init__(
        self,
        rows: Optional[Dict[str, Any]] = None,
        fail_on: Optional[Callable[[str], bool]] = None,
        error: Optional[BaseException] = None,
        session_error: Optional[BaseException] = None,
    ):
        self.rows: Dict[str, Any] = rows or {}
        self.fail_on = fail_on
        self.error = error or RuntimeError("fake driver: simulated Neo4j failure")
        self.session_error = session_error
        self.calls: List[tuple] = []

    def session(self, **kwargs: Any) -> FakeReadSession:
        return FakeReadSession(self, kwargs.get("database"))

    def names(self) -> List[str]:
        return [name for name, _ in self.calls]


def down_driver() -> FakeReadDriver:
    """A driver whose every session fails like an unreachable server."""
    try:
        from neo4j.exceptions import ServiceUnavailable

        err: BaseException = ServiceUnavailable("Couldn't connect to localhost:7687")
    except Exception:  # pragma: no cover - neo4j not installed
        err = OSError("connection refused")
    return FakeReadDriver(session_error=err)


# ---------------------------------------------------------------------------
# Canned graph rows
# ---------------------------------------------------------------------------
def overview_row(rid: str, decision: str, *, claims: int = 1, supported: int = 0,
                 reason_codes: Iterable[str] = (), topic: Optional[str] = None,
                 created_at: Optional[str] = None, query_preview: Optional[str] = None):
    return {
        "request_id": rid, "decision": decision, "created_at": created_at,
        "topic": topic, "query_preview": query_preview,
        "reason_codes": list(reason_codes), "claims": claims,
        "supported_claims": supported,
    }


def usage_row(rid: str, doc_id: str, *, decision: str = "ANSWER", source: Optional[str] = None,
              version: Optional[str] = None, date: Optional[str] = None,
              created_at: Optional[str] = None, supported_by_doc: int = 0,
              contradicted_by_doc: int = 0, vias: Iterable[str] = ("retrieved",),
              texts: Iterable[str] = ()):
    return {
        "request_id": rid, "decision": decision, "created_at": created_at,
        "doc_id": doc_id, "source": source, "version": version, "date": date,
        "vias": list(vias), "supported_by_doc": supported_by_doc,
        "supported_claim_texts": list(texts), "contradicted_by_doc": contradicted_by_doc,
    }


def conflict_row(rid: str, doc_a: str, doc_b: str, *, decision: str = "ESCALATE",
                 kind: str = "numeric", value_a: Any = "20", value_b: Any = "25"):
    return {
        "request_id": rid, "decision": decision, "doc_a": doc_a, "source_a": doc_a[4:],
        "doc_b": doc_b, "source_b": doc_b[4:], "kind": kind,
        "value_a": value_a, "value_b": value_b,
    }


def doc_row(doc_id: str, source: Optional[str] = None, version: Optional[str] = None,
            date: Optional[str] = None):
    return {"doc_id": doc_id, "source": source, "version": version, "date": date}


# ---------------------------------------------------------------------------
# Audit DB seeding
# ---------------------------------------------------------------------------
def seed_audit(db_path: str, records: Iterable[Dict[str, Any]]) -> None:
    """Insert audit rows directly (request_id, timestamp, decision, query, reason_codes)."""
    from app.audit import AuditLogger

    AuditLogger(db_path)  # creates the schema
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for rec in records:
                conn.execute(
                    "INSERT INTO audit_logs (request_id, timestamp, query, decision, "
                    "reason_codes, profile) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        rec["request_id"], rec["timestamp"], rec.get("query"),
                        rec.get("decision"), json.dumps(rec.get("reason_codes", [])),
                        "standard",
                    ),
                )
    finally:
        conn.close()
