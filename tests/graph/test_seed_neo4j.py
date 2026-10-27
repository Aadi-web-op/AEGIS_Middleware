"""Unit tests for the Neo4j seeding script.

Tests running benchmark cases into the sink using fake drivers without requiring a running database.
"""

from __future__ import annotations

import pytest
from app.core.evaluator import Evaluator
from app.evidence.stubs import FixedSignal
from app.graph.neo4j_sink import Neo4jGraphSink
from scripts.seed_neo4j import build_trace_for_case, seed_cases
from tests.benchmark.test_cases import DEV_CASES
from tests.graph.fake_driver import FakeDriver


def _mock_evaluator() -> Evaluator:
    """Fast mock evaluator with fixed signals so tests don't load heavyweight models."""
    signals = [
        FixedSignal("relevance", 0.9),
        FixedSignal("entailment", 0.85),
        FixedSignal("contradiction", 0.05),
        FixedSignal("freshness", 0.95),
        FixedSignal("completeness", 0.9),
        FixedSignal("ambiguity", 0.05),
    ]
    return Evaluator(signals)


def test_build_trace_for_benchmark_case():
    """Verify build_trace_for_case builds a valid trace according to the contract."""
    evaluator = _mock_evaluator()
    case = DEV_CASES[0]

    trace = build_trace_for_case(evaluator, case)
    assert trace["request_id"] == f"bench-{case['name']}"
    assert trace["decision"] in {"ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"}
    assert "headline" in trace and trace["headline"]
    assert len(trace["nodes"]) >= 1
    assert any(n["type"] == "Decision" for n in trace["nodes"])


def test_seed_cases_with_fake_sink():
    """Verify seed_cases iterates through dev cases and writes traces into the sink."""
    driver = FakeDriver()
    sink = Neo4jGraphSink(driver)
    evaluator = _mock_evaluator()

    summary = seed_cases(sink=sink, cases=DEV_CASES[:3], evaluator=evaluator)

    assert summary["total_cases"] == 3
    assert summary["successful_writes"] == 3
    assert summary["failed_writes"] == 0
    assert len(summary["seeded_request_ids"]) == 3
    # Check that driver executed MERGE statements
    assert len(driver.calls) > 0
    assert any(c.is_node_merge for c in driver.calls)


def test_seed_cases_idempotent():
    """Verify re-running seed_cases issues MERGE statements without error."""
    driver = FakeDriver()
    sink = Neo4jGraphSink(driver)
    evaluator = _mock_evaluator()

    summary1 = seed_cases(sink=sink, cases=DEV_CASES[:2], evaluator=evaluator)
    summary2 = seed_cases(sink=sink, cases=DEV_CASES[:2], evaluator=evaluator)

    assert summary1["successful_writes"] == 2
    assert summary2["successful_writes"] == 2
