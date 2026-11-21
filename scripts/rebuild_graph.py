"""Rebuild the Neo4j decision graph from the SQLite audit log.

The audit log is the system of record; the graph is a projection of it.
Every evaluation's full response -- including its decision trace -- is
stored in `audit_logs.response_json`. This script replays those traces
into Neo4j through the same writer live requests use.

It is idempotent (every write is a MERGE and a Decision's `created_at`
is first-write-wins) and it never deletes anything, so it is safe to run
against a populated graph: to recover traces the background writer
dropped, after a Neo4j outage, or to fill an empty database.

Rows without `response_json` (logged before that column existed, or
generation failures) carry no trace and are skipped and counted.

Usage:
    python -m scripts.rebuild_graph [--db audit.db] [--uri bolt://localhost:7687]
                                    [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sqlite3
import sys
from typing import Any, Dict, Iterator, Optional

from app.graph.contract import TraceContractError, validate_trace
from app.graph.sink import safe_write_trace
from app.graph.topics import topic_key
from app.graph.trace_builder import query_preview

logger = logging.getLogger("rebuild_graph")


def _default_db_path() -> str:
    from app.audit import default_audit_db_path

    return str(default_audit_db_path())


def iter_audit_rows(db_path: str, limit: Optional[int] = None) -> Iterator[Dict[str, Any]]:
    """Yield audit rows oldest-first, so supersession history replays in order."""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "audit_logs" not in tables:
            return
        columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_logs)")}
        wanted = [c for c in ("request_id", "timestamp", "query", "response_json") if c in columns]
        sql = f"SELECT {', '.join(wanted)} FROM audit_logs ORDER BY timestamp ASC"
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (int(limit),)
        for row in conn.execute(sql, params):
            yield dict(row)
    finally:
        conn.close()


def trace_from_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The decision trace stored in an audit row, upgraded for replay.

    Returns None when the row has no usable trace. For traces written
    before trace v2, the Decision's `created_at`, `query_preview` and
    `topic` are filled from the row's own (already sanitised) columns --
    never invented.
    """
    raw = row.get("response_json")
    if not raw:
        return None
    try:
        response = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(response, dict) or not isinstance(response.get("trace"), dict):
        return None

    trace = copy.deepcopy(response["trace"])
    request_id = trace.get("request_id")
    for node in trace.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "Decision":
            continue
        if node.get("id") != request_id and node.get("request_id") != request_id:
            continue
        if not node.get("created_at") and row.get("timestamp"):
            node["created_at"] = str(row["timestamp"])
        if not node.get("query_preview"):
            preview = query_preview(row.get("query"))
            if preview:
                node["query_preview"] = preview
        if not node.get("topic"):
            topic = topic_key(row.get("query"))
            if topic:
                node["topic"] = topic
        if "degraded" not in node and isinstance(response.get("degraded"), bool):
            node["degraded"] = response["degraded"]
    return trace


def rebuild(sink: Any, db_path: str, limit: Optional[int] = None, dry_run: bool = False) -> Dict[str, int]:
    """Replay every stored trace in `db_path` into `sink`. Returns counters."""
    summary = {
        "rows": 0,
        "replayed": 0,
        "skipped_no_trace": 0,
        "skipped_invalid": 0,
        "failed": 0,
    }
    for row in iter_audit_rows(db_path, limit):
        summary["rows"] += 1
        trace = trace_from_row(row)
        if trace is None:
            summary["skipped_no_trace"] += 1
            continue
        try:
            validate_trace(trace)
        except TraceContractError as exc:
            summary["skipped_invalid"] += 1
            logger.warning("Skipping %s: %s", row.get("request_id"), exc)
            continue
        if dry_run:
            summary["replayed"] += 1
            continue
        if safe_write_trace(sink, trace):
            summary["replayed"] += 1
        else:
            summary["failed"] += 1
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Rebuild the Neo4j decision graph from audit.db.")
    parser.add_argument("--db", default=None, help="Audit database path (default: AEGIS_AUDIT_DB_PATH or ./audit.db)")
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "password"))
    parser.add_argument("--database", default=None, help="Optional Neo4j database name")
    parser.add_argument("--limit", type=int, default=None, help="Replay at most N rows (oldest first)")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate only; write nothing")
    args = parser.parse_args()

    db_path = args.db or _default_db_path()
    if not os.path.exists(db_path):
        logger.error("Audit database %s does not exist", db_path)
        sys.exit(1)

    sink = None
    if not args.dry_run:
        from app.graph.neo4j_sink import Neo4jGraphSink
        from app.graph.schema import apply_schema

        try:
            sink = Neo4jGraphSink.from_uri(args.uri, args.user, args.password, database=args.database)
            sink.driver.verify_connectivity()
            apply_schema(sink.driver, database=args.database)
        except Exception as exc:
            logger.error("Could not connect to Neo4j at %s: %s", args.uri, exc)
            sys.exit(1)

    summary = rebuild(sink, db_path, limit=args.limit, dry_run=args.dry_run)
    if sink is not None:
        sink.close()

    logger.info("Rebuild %s: %s", "dry run" if args.dry_run else "complete", summary)
    print(json.dumps(summary))
    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
