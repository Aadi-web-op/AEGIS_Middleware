"""Unit tests for Neo4j schema definitions and the five insight queries.

Runs against mock/fake drivers without requiring a running Neo4j instance.
"""

from __future__ import annotations

import pytest
from typing import Any, Dict, List, Optional

from app.graph.insights import (
    conflicting_document_pairs,
    escalations_by_root_cause,
    frequent_abstain_topics,
    impacted_decisions_for_document,
    outdated_documents_retrieved,
)
from app.graph.schema import (
    ALL_SCHEMA_STATEMENTS,
    CONSTRAINTS,
    INDEXES,
    apply_schema,
)
from tests.graph.fake_driver import FakeDriver


class RecordMock:
    """Mocks a Neo4j Record object."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def data(self) -> Dict[str, Any]:
        return dict(self._data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]


class MockQueryDriver:
    """A driver that returns scripted records for specific Cypher queries."""

    def __init__(self, canned_results: Optional[List[Dict[str, Any]]] = None):
        self.canned_results = canned_results or []
        self.recorded_queries: List[tuple[str, Dict[str, Any]]] = []

    def session(self, **kwargs: Any) -> "MockQuerySession":
        return MockQuerySession(self)


class MockQuerySession:
    def __init__(self, driver: MockQueryDriver):
        self._driver = driver

    def __enter__(self) -> "MockQuerySession":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def run(self, cypher: str, **params: Any) -> List[RecordMock]:
        self._driver.recorded_queries.append((cypher, dict(params)))
        return [RecordMock(r) for r in self._driver.canned_results]

    def execute_read(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        class FakeReadTx:
            def __init__(self, session: MockQuerySession):
                self._session = session

            def run(self, cypher: str, **params: Any) -> List[RecordMock]:
                return self._session.run(cypher, **params)

        return fn(FakeReadTx(self), *args, **kwargs)


# ---------------------------------------------------------------------------
# Schema Tests
# ---------------------------------------------------------------------------
def test_schema_statements_defined():
    """Verify constraints and indexes are declared per the team brief."""
    assert len(CONSTRAINTS) == 5
    assert len(INDEXES) >= 5
    assert len(ALL_SCHEMA_STATEMENTS) == len(CONSTRAINTS) + len(INDEXES)

    for stmt in CONSTRAINTS:
        assert stmt.startswith("CREATE CONSTRAINT")
        assert "IF NOT EXISTS" in stmt

    for stmt in INDEXES:
        assert stmt.startswith("CREATE INDEX")
        assert "IF NOT EXISTS" in stmt


def test_apply_schema_executes_all_statements():
    """Verify apply_schema runs every constraint and index through the driver."""
    driver = FakeDriver()
    executed = apply_schema(driver)

    assert len(executed) == len(ALL_SCHEMA_STATEMENTS)
    assert len(driver.calls) == len(ALL_SCHEMA_STATEMENTS)
    # Check key constraints were run
    called_cyphers = [call.cypher for call in driver.calls]
    assert any("FOR (d:Decision) REQUIRE d.request_id IS UNIQUE" in c for c in called_cyphers)
    assert any("FOR (d:Document) REQUIRE d.id IS UNIQUE" in c for c in called_cyphers)


# ---------------------------------------------------------------------------
# Insight Query 1: Conflicting Document Pairs
# ---------------------------------------------------------------------------
def test_conflicting_document_pairs_query():
    fake_rows = [
        {
            "source_a": "hr-policy.pdf",
            "version_a": "2023.1",
            "doc_a": "doc:hr-policy.pdf@2023.1",
            "source_b": "hr-policy.pdf",
            "version_b": "2024.2",
            "doc_b": "doc:hr-policy.pdf@2024.2",
            "conflict_kinds": ["numeric"],
            "conflict_count": 3,
        }
    ]
    driver = MockQueryDriver(fake_rows)
    results = conflicting_document_pairs(driver, limit=5)

    assert len(results) == 1
    assert results[0]["source_a"] == "hr-policy.pdf"
    assert results[0]["conflict_count"] == 3

    cypher, params = driver.recorded_queries[0]
    assert "CONFLICTS_WITH" in cypher
    assert "[:FROM]->(d1:Document)" in cypher
    assert params["limit"] == 5


# ---------------------------------------------------------------------------
# Insight Query 2: Outdated Documents Retrieved
# ---------------------------------------------------------------------------
def test_outdated_documents_retrieved_query():
    fake_rows = [
        {
            "source": "leave-rules.pdf",
            "outdated_version": "v1",
            "outdated_doc_id": "doc:leave-rules.pdf@v1",
            "newer_version": "v2",
            "newer_doc_id": "doc:leave-rules.pdf@v2",
            "retrieved_chunk_count": 4,
            "affected_decisions_count": 2,
        }
    ]
    driver = MockQueryDriver(fake_rows)
    results = outdated_documents_retrieved(driver, limit=10)

    assert len(results) == 1
    assert results[0]["outdated_version"] == "v1"
    assert results[0]["newer_version"] == "v2"

    cypher, params = driver.recorded_queries[0]
    assert "SUPERSEDES" in cypher
    assert "[:FROM]->(older:Document)" in cypher
    assert params["limit"] == 10


# ---------------------------------------------------------------------------
# Insight Query 3: Frequent ABSTAIN Topics
# ---------------------------------------------------------------------------
def test_frequent_abstain_topics_query():
    fake_rows = [
        {
            "reason_code": "NO_EVIDENCE",
            "sample_reason": "No evidence was provided.",
            "sample_claims": ["Brazil won the 2035 World Cup."],
            "sample_request_ids": ["req-001"],
            "abstain_count": 5,
        }
    ]
    driver = MockQueryDriver(fake_rows)
    results = frequent_abstain_topics(driver, limit=10)

    assert len(results) == 1
    assert results[0]["reason_code"] == "NO_EVIDENCE"
    assert results[0]["abstain_count"] == 5

    cypher, params = driver.recorded_queries[0]
    assert "decision: 'ABSTAIN'" in cypher
    assert "BECAUSE" in cypher


# ---------------------------------------------------------------------------
# Insight Query 4: Impacted Decisions for Document
# ---------------------------------------------------------------------------
def test_impacted_decisions_for_document_query():
    fake_rows = [
        {
            "source": "hr-policy.pdf",
            "version": "v3",
            "doc_id": "doc:hr-policy.pdf@v3",
            "affected_request_ids": ["req-101", "req-102"],
            "decisions": [
                {"request_id": "req-101", "decision": "ANSWER", "score": 0.95},
                {"request_id": "req-102", "decision": "CAVEAT", "score": 0.72},
            ],
            "total_affected_decisions": 2,
        }
    ]
    driver = MockQueryDriver(fake_rows)
    result = impacted_decisions_for_document(driver, source="hr-policy.pdf", version="v3")

    assert result["source"] == "hr-policy.pdf"
    assert result["total_affected_decisions"] == 2
    assert "req-101" in result["affected_request_ids"]

    cypher, params = driver.recorded_queries[0]
    assert "SUPPORTED_BY" in cypher
    assert "HAS_CLAIM" in cypher
    assert params["source"] == "hr-policy.pdf"
    assert params["version"] == "v3"


def test_impacted_decisions_for_document_not_found():
    """Verify empty/zero structure when no document matches."""
    driver = MockQueryDriver([])
    result = impacted_decisions_for_document(driver, source="nonexistent.pdf")

    assert result["source"] == "nonexistent.pdf"
    assert result["total_affected_decisions"] == 0
    assert result["decisions"] == []


# ---------------------------------------------------------------------------
# Insight Query 5: Escalations by Root Cause
# ---------------------------------------------------------------------------
def test_escalations_by_root_cause_query():
    fake_rows = [
        {
            "source": "circular_2025.txt",
            "version": "1.0",
            "doc_id": "doc:circular_2025.txt@1.0",
            "root_cause_code": "CONTRADICTION",
            "sample_messages": ["Evidence sources directly conflict about the current status."],
            "escalation_request_ids": ["req-esc-1", "req-esc-2"],
            "escalation_count": 2,
        }
    ]
    driver = MockQueryDriver(fake_rows)
    results = escalations_by_root_cause(driver, limit=5)

    assert len(results) == 1
    assert results[0]["root_cause_code"] == "CONTRADICTION"
    assert results[0]["escalation_count"] == 2

    cypher, params = driver.recorded_queries[0]
    assert "decision: 'ESCALATE'" in cypher
    assert "BECAUSE" in cypher
    assert "ABOUT" in cypher
