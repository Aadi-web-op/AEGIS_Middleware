"""Seeding script for Neo4j: runs benchmark dev set through Aegis into Neo4j.

Per "Aegis Decision Graph (Neo4j Add-on): Team Brief" (Oct 22, 2026):
"The insights must come from real runs, not hand-made data. Shatakshi's seeding
script runs the benchmark dev set through Aegis and writes every trace to Neo4j,
so the demo panel shows what our own system produced."

Usage:
    python -m scripts.seed_neo4j [--uri bolt://localhost:7687] [--user neo4j] [--password password]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.graph.neo4j_sink import Neo4jGraphSink
from app.graph.schema import apply_schema
from app.graph.sink import safe_write_trace
from app.graph.trace_builder import build_trace
from tests.benchmark.test_cases import BENCHMARK_CASES, DEV_CASES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_neo4j")

# Headings from page 5 of the Team Brief
HEADLINES: Dict[str, str] = {
    "ANSWER": "Safe to show. Every statement in the answer is backed by current documents.",
    "CAVEAT": "Mostly backed up, but something needs a warning.",
    "ESCALATE": "A person should check this before anyone relies on it.",
    "ABSTAIN": "We could not find enough in your documents to answer.",
}


def build_trace_for_case(
    evaluator: Evaluator,
    case: Dict[str, Any],
) -> Dict[str, Any]:
    """Run a single benchmark case through Evaluator and construct its decision-graph trace."""
    req = case["request"]
    request_id = f"bench-{case['name']}"

    # Evaluate using the full pipeline
    response = evaluator.evaluate(req)

    # Collect signal details for trace building
    signal_results = {
        s.name: s.run(req.query, req.answer, req.evidence)
        for s in evaluator.signals
    }

    entailment_details = signal_results.get("entailment").details if "entailment" in signal_results else None
    contradiction_details = signal_results.get("contradiction").details if "contradiction" in signal_results else None

    evidence_payload = [item.model_dump() for item in req.evidence]
    reasons_payload = [{"code": r.code.value, "message": r.message} for r in response.reasons]
    decision_val = response.decision.value
    headline = HEADLINES.get(decision_val, "Decision returned by Aegis.")

    trace = build_trace(
        request_id=request_id,
        decision=decision_val,
        headline=headline,
        evidence=evidence_payload,
        entailment_details=entailment_details,
        contradiction_details=contradiction_details,
        reasons=reasons_payload,
        answerability_score=response.answerability_score,
        policy_version=response.policy_version,
        profile=req.profile,
    )
    return trace


def seed_cases(
    sink: Any,
    cases: Optional[Sequence[Dict[str, Any]]] = None,
    evaluator: Optional[Evaluator] = None,
) -> Dict[str, Any]:
    """Seed benchmark cases into Neo4j using the given sink.

    Args:
        sink: A GraphSink (e.g. Neo4jGraphSink) or driver-backed sink.
        cases: List of cases to seed (defaults to DEV_CASES).
        evaluator: Evaluator instance to use.

    Returns:
        Summary dict of total cases, successes, failures, and request_ids.
    """
    if cases is None:
        cases = DEV_CASES

    if evaluator is None:
        evaluator = Evaluator(default_signals())

    success_count = 0
    failure_count = 0
    seeded_ids: List[str] = []

    logger.info("Starting seeding of %d benchmark cases into Neo4j...", len(cases))

    for idx, case in enumerate(cases):
        name = case["name"]
        try:
            trace = build_trace_for_case(evaluator, case)
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
        "seeded_request_ids": seeded_ids,
    }
    logger.info(
        "Seeding complete: %d succeeded, %d failed out of %d total cases",
        success_count,
        failure_count,
        len(cases),
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
    args = parser.parse_args()

    cases = BENCHMARK_CASES if args.all_cases else DEV_CASES

    try:
        sink = Neo4jGraphSink.from_uri(
            uri=args.uri,
            user=args.user,
            password=args.password,
            database=args.database,
        )
        sink._driver.verify_connectivity()
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
            apply_schema(sink._driver, database=args.database)
        except Exception as exc:
            logger.warning("Could not apply schema (may already exist or insufficient permissions): %s", exc)

    summary = seed_cases(sink=sink, cases=cases)
    sink.close()

    if summary["failed_writes"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
