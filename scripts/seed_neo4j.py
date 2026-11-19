"""Seeding script for Neo4j: runs benchmark & synthetic HR requests through Aegis into Neo4j.

Per "AEGIS Finale Plan: Decisions & Task Split" (Nov 17, 2026):
"Seed script: 30 to 50 varied requests through /v1/evaluate; re-run once hash identity is merged (2h)
Seed data: 30 to 50 synthetic requests over the existing HR documents, so the graph
and Insights have something to show."

Supports two execution modes:
1. Direct evaluation (default / offline): Evaluates via local Evaluator pipeline and writes traces.
2. HTTP evaluation: Posts requests to a live /v1/evaluate server (`--api-url http://localhost:8000`).

Usage:
    python -m scripts.seed_neo4j [--uri bolt://localhost:7687] [--user neo4j] [--password password]
    python -m scripts.seed_neo4j --api-url http://127.0.0.1:8000
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
from data.synthetic_cases import SYNTHETIC_HR_CASES, get_all_seed_cases
from tests.benchmark.test_cases import BENCHMARK_CASES, DEV_CASES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_neo4j")

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
    """Run a single case through Evaluator and construct its decision-graph trace."""
    req = case["request"]
    request_id = f"bench-{case['name']}"

    response = evaluator.evaluate(req)

    signal_results = {
        s.name: s.run(req.query, req.answer, req.evidence)
        for s in evaluator.signals
    }

    entailment_details = (
        signal_results.get("entailment").details if "entailment" in signal_results else None
    )
    contradiction_details = (
        signal_results.get("contradiction").details if "contradiction" in signal_results else None
    )

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


def seed_via_http(
    api_url: str,
    cases: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Seed cases by POSTing to a running /v1/evaluate server endpoint."""
    import httpx

    endpoint = f"{api_url.rstrip('/')}/v1/evaluate"
    logger.info("Seeding %d cases through live endpoint: %s", len(cases), endpoint)

    success_count = 0
    failure_count = 0
    seeded_ids: List[str] = []

    with httpx.Client(timeout=30.0) as client:
        for idx, case in enumerate(cases):
            name = case["name"]
            req_data = case["request"].model_dump()
            try:
                resp = client.post(endpoint, json=req_data)
                if resp.status_code == 200:
                    data = resp.json()
                    success_count += 1
                    req_id = data.get("request_id", f"bench-{name}")
                    seeded_ids.append(req_id)
                    logger.info(
                        "[%d/%d] HTTP Seeded %s -> %s (score: %s)",
                        idx + 1,
                        len(cases),
                        name,
                        data.get("decision"),
                        data.get("answerability_score"),
                    )
                else:
                    failure_count += 1
                    logger.warning(
                        "[%d/%d] HTTP Failed %s: status %d - %s",
                        idx + 1,
                        len(cases),
                        name,
                        resp.status_code,
                        resp.text[:120],
                    )
            except Exception as exc:
                failure_count += 1
                logger.exception("[%d/%d] HTTP Error on %s: %s", idx + 1, len(cases), name, exc)

    return {
        "total_cases": len(cases),
        "successful_writes": success_count,
        "failed_writes": failure_count,
        "seeded_request_ids": seeded_ids,
    }


def seed_cases(
    sink: Any,
    cases: Optional[Sequence[Dict[str, Any]]] = None,
    evaluator: Optional[Evaluator] = None,
) -> Dict[str, Any]:
    """Seed benchmark cases into Neo4j using the given sink.

    Args:
        sink: A GraphSink (e.g. Neo4jGraphSink) or driver-backed sink.
        cases: List of cases to seed (defaults to combined dev + synthetic cases).
        evaluator: Evaluator instance to use.

    Returns:
        Summary dict of total cases, successes, failures, and request_ids.
    """
    if cases is None:
        cases = get_all_seed_cases()

    if evaluator is None:
        evaluator = Evaluator(default_signals())

    success_count = 0
    failure_count = 0
    seeded_ids: List[str] = []

    logger.info("Starting direct seeding of %d cases into Neo4j...", len(cases))

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
    parser = argparse.ArgumentParser(description="Seed Aegis Decision Graph into Neo4j.")
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
        "--dev-only",
        action="store_true",
        help="Seed only canonical 12 dev cases instead of full 47 cases",
    )
    parser.add_argument(
        "--all-benchmark",
        action="store_true",
        help="Seed all 20 benchmark cases",
    )
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        default=True,
        help="Apply constraints and indexes before seeding (default True)",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="Optional URL of running Aegis server (e.g. http://127.0.0.1:8000) to seed via /v1/evaluate",
    )
    args = parser.parse_args()

    if args.dev_only:
        cases = DEV_CASES
    elif args.all_benchmark:
        cases = BENCHMARK_CASES
    else:
        cases = get_all_seed_cases()

    # Mode 1: HTTP API Seeding
    if args.api_url:
        summary = seed_via_http(args.api_url, cases)
        if summary["failed_writes"] > 0:
            sys.exit(1)
        return

    # Mode 2: Direct Neo4j Bolt Seeding
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
                "Neo4j authentication failed: Incorrect password or username for %s (user: '%s').",
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
            logger.warning("Could not apply schema: %s", exc)

    summary = seed_cases(sink=sink, cases=cases)
    sink.close()

    if summary["failed_writes"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
