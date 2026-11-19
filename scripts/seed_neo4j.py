"""Seeding script for Neo4j: runs benchmark dev set through Aegis into Neo4j.

Per "Aegis Decision Graph (Neo4j Add-on): Team Brief" (Oct 22, 2026):
"The insights must come from real runs, not hand-made data. Shatakshi's seeding
script runs the benchmark dev set through Aegis and writes every trace to Neo4j,
so the demo panel shows what our own system produced."

Each case is evaluated exactly once by the real `Evaluator`, and the trace
written is the one the evaluator itself produced (`response.trace`) -- the
same trace a live request would persist -- under the stable request id
`bench-<case name>`. Because ids are stable and every write is a MERGE,
re-running the script creates no duplicates.

By default every seeded decision is also recorded in the SQLite audit log
under the same request id, so the graph stays a rebuildable projection of
the audit log (`scripts/rebuild_graph.py`). Pass `--no-audit` to skip that.

Usage:
    python -m scripts.seed_neo4j [--uri bolt://localhost:7687] [--user neo4j] [--password password]
"""

from __future__ import annotations

import argparse
import copy
import inspect
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.graph.neo4j_sink import Neo4jGraphSink
from app.graph.schema import apply_schema
from app.graph.sink import safe_write_trace
from tests.benchmark.test_cases import BENCHMARK_CASES, DEV_CASES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_neo4j")

REQUEST_ID_PREFIX = "bench-"


def case_request_id(case: Dict[str, Any]) -> str:
    """Stable request id for a benchmark case."""
    return f"{REQUEST_ID_PREFIX}{case['name']}"


def rekey_trace(trace: Dict[str, Any], new_request_id: str) -> Dict[str, Any]:
    """Return a copy of `trace` whose request id is `new_request_id`.

    Request-scoped node ids (`<request_id>`, `<request_id>:claim:0`, ...)
    are rewritten; global ids (Document ids, chunk ids) are left alone.
    """
    old = trace.get("request_id")
    clone = copy.deepcopy(trace)
    if not isinstance(old, str) or not old or old == new_request_id:
        return clone

    def _swap(value: Any) -> Any:
        if isinstance(value, str):
            if value == old:
                return new_request_id
            if value.startswith(old + ":"):
                return new_request_id + value[len(old):]
        return value

    clone["request_id"] = new_request_id
    for node in clone.get("nodes") or []:
        node["id"] = _swap(node.get("id"))
        if "request_id" in node:
            node["request_id"] = _swap(node["request_id"])
    for edge in clone.get("edges") or []:
        edge["from"] = _swap(edge.get("from"))
        edge["to"] = _swap(edge.get("to"))
    return clone


def evaluate_case(evaluator: Evaluator, case: Dict[str, Any]) -> Any:
    """Run one case through the evaluator; the response carries the stable id."""
    request = case["request"]
    request_id = case_request_id(case)

    if "request_id" in inspect.signature(evaluator.evaluate).parameters:
        return evaluator.evaluate(request, request_id=request_id)

    # Older evaluator: it mints its own id, so re-key the response and trace.
    response = evaluator.evaluate(request)
    update: Dict[str, Any] = {"request_id": request_id}
    if response.trace is not None:
        update["trace"] = rekey_trace(response.trace, request_id)
    return response.model_copy(update=update)


def build_trace_for_case(
    evaluator: Evaluator,
    case: Dict[str, Any],
) -> Dict[str, Any]:
    """Run a single benchmark case through Evaluator and return its decision trace."""
    response = evaluate_case(evaluator, case)
    if response.trace is None:
        raise RuntimeError(f"Evaluator produced no trace for case {case['name']!r}")
    return response.trace


def seed_cases(
    sink: Any,
    cases: Optional[Sequence[Dict[str, Any]]] = None,
    evaluator: Optional[Evaluator] = None,
    audit_logger: Any = None,
) -> Dict[str, Any]:
    """Seed benchmark cases into Neo4j using the given sink.

    Args:
        sink: A GraphSink (e.g. Neo4jGraphSink) or driver-backed sink.
        cases: List of cases to seed (defaults to DEV_CASES).
        evaluator: Evaluator instance to use.
        audit_logger: Optional `AuditLogger`; when given, each seeded
            decision is also recorded there under the same request id.

    Returns:
        Summary dict of total cases, successes, failures, and request_ids.
    """
    if cases is None:
        cases = DEV_CASES

    if evaluator is None:
        evaluator = Evaluator(default_signals())

    success_count = 0
    failure_count = 0
    audit_count = 0
    seeded_ids: List[str] = []

    logger.info("Starting seeding of %d benchmark cases into Neo4j...", len(cases))

    for idx, case in enumerate(cases):
        name = case["name"]
        try:
            response = evaluate_case(evaluator, case)
            trace = response.trace
            if trace is None:
                raise RuntimeError("evaluator produced no trace")

            if audit_logger is not None:
                if audit_logger.log_evaluation(case["request"], response):
                    audit_count += 1
                else:
                    logger.warning("Could not record %s in the audit log", name)

            ok = safe_write_trace(sink, trace)
            if ok:
                success_count += 1
                seeded_ids.append(trace["request_id"])
                logger.info(
                    "[%d/%d] Seeded %s (decision: %s, nodes: %d, edges: %d)",
                    idx + 1,
                    len(cases),
                    name,
                    trace["decision"],
                    len(trace["nodes"]),
                    len(trace["edges"]),
                )
            else:
                failure_count += 1
                logger.warning("[%d/%d] Failed to write trace for %s", idx + 1, len(cases), name)
        except Exception:
            failure_count += 1
            logger.exception("[%d/%d] Exception during seeding of %s", idx + 1, len(cases), name)

    summary = {
        "total_cases": len(cases),
        "successful_writes": success_count,
        "failed_writes": failure_count,
        "audit_records": audit_count,
        "seeded_request_ids": seeded_ids,
    }
    logger.info(
        "Seeding complete: %d succeeded, %d failed out of %d total cases (%d audit records)",
        success_count,
        failure_count,
        len(cases),
        audit_count,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Aegis benchmark dev set into Neo4j.")
    parser.add_argument(
        "--uri",
        default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        help="Neo4j Bolt URI",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("NEO4J_USER", "neo4j"),
        help="Neo4j username",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("NEO4J_PASSWORD", "password"),
        help="Neo4j password",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Optional Neo4j database name",
    )
    parser.add_argument(
        "--all-cases",
        action="store_true",
        help="Seed all benchmark cases instead of only DEV_CASES",
    )
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        default=True,
        help="Apply constraints and indexes before seeding (default True)",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Do not record seeded decisions in the SQLite audit log",
    )
    parser.add_argument(
        "--audit-db",
        default=None,
        help="Audit database path (default: AEGIS_AUDIT_DB_PATH or ./audit.db)",
    )
    args = parser.parse_args()

    cases = BENCHMARK_CASES if args.all_cases else DEV_CASES

    try:
        sink = Neo4jGraphSink.from_uri(
            uri=args.uri,
            user=args.user,
            password=args.password,
            database=args.database,
        )
        sink.driver.verify_connectivity()
    except Exception as exc:
        err_msg = str(exc)
        if "Unauthorized" in err_msg or "AuthError" in type(exc).__name__:
            logger.error(
                "Neo4j authentication failed: Incorrect password or username for %s (user: '%s').\n"
                "  - If using Neo4j AuraDB (cloud), make sure to use the instance password from the downloaded credentials .txt file (not your account login password).\n"
                "  - Supply password via: --password <your_password> or $env:NEO4J_PASSWORD=\"<your_password>\"",
                args.uri,
                args.user,
            )
        else:
            logger.error("Failed to connect to Neo4j at %s: %s", args.uri, exc)
        sys.exit(1)

    if args.apply_schema:
        logger.info("Applying constraints and indexes to Neo4j...")
        try:
            apply_schema(sink.driver, database=args.database)
        except Exception as exc:
            logger.warning("Could not apply schema (may already exist or insufficient permissions): %s", exc)

    audit_logger = None
    if not args.no_audit:
        from app.audit import AuditLogger

        audit_logger = AuditLogger(args.audit_db) if args.audit_db else AuditLogger()
        logger.info("Recording seeded decisions in the audit log at %s", audit_logger.db_path)

    summary = seed_cases(sink=sink, cases=cases, audit_logger=audit_logger)
    sink.close()

    if summary["failed_writes"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
