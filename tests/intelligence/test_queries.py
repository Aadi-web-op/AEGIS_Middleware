"""The named Cypher queries are parameterised and run correctly in a read tx."""

from __future__ import annotations

import inspect
import re

import pytest

from app.intelligence import queries, service
from app.intelligence.queries import QUERIES
from tests.intelligence.fakes import FakeReadDriver

DECISION_SCOPED = {"decision_overview", "decision_document_usage", "conflict_edges",
                   "escalation_root_causes", "graph_decision_count"}


def test_queries_are_static_strings_with_parameters_only():
    for name, cypher in QUERIES.items():
        assert isinstance(cypher, str)
        # no Python formatting placeholders left in the text
        assert "{prefix" not in cypher and "%s" not in cypher, name
        # user-supplied values only ever enter as $parameters
        params = set(re.findall(r"\$(\w+)", cypher))
        assert params <= {"prefix", "limit", "doc_id"}, (name, params)


@pytest.mark.parametrize("name", sorted(DECISION_SCOPED))
def test_decision_queries_are_scoped_by_prefix(name):
    assert "STARTS WITH $prefix" in QUERIES[name]


def test_row_returning_queries_are_bounded():
    for name, cypher in QUERIES.items():
        if name != "graph_decision_count":
            assert "LIMIT" in cypher, name


def test_service_never_builds_cypher_dynamically():
    src = inspect.getsource(service)
    assert "MATCH" not in src  # all Cypher lives in queries.QUERIES


def test_run_passes_plain_string_and_parameters_to_managed_read():
    # The fake tx rejects non-str queries exactly like neo4j's ManagedTransaction
    # (a neo4j.Query object inside execute_read raises TypeError).
    driver = FakeReadDriver({"documents": [{"doc_id": "doc:a"}]})
    rows = queries.run(driver, "documents", {"prefix": "x'; DETACH DELETE n //"})
    assert rows == [{"doc_id": "doc:a"}]
    (name, params), = driver.calls
    assert name == "documents"
    assert params["prefix"] == "x'; DETACH DELETE n //"  # a value, never spliced into text
    assert params["limit"] == queries.DEFAULT_ROW_LIMIT and params["doc_id"] is None


def test_run_attaches_transaction_timeout():
    seen = {}

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute_read(self, fn):
            seen["timeout"] = getattr(fn, "timeout", None)
            return []

    class Driver:
        def session(self, **kw):
            seen["kw"] = kw
            return Session()

    queries.run(Driver(), "documents", database="neo4j")
    assert seen["kw"] == {"database": "neo4j"}
    pytest.importorskip("neo4j")
    assert seen["timeout"] == queries.QUERY_TIMEOUT_S


def test_temporal_values_become_iso_strings():
    class FakeDateTime:
        def iso_format(self):
            return "2026-04-01T00:00:00Z"

    rows = queries._to_dicts([{"created_at": FakeDateTime(), "xs": [FakeDateTime()], "n": 1}])
    assert rows == [{"created_at": "2026-04-01T00:00:00Z", "xs": ["2026-04-01T00:00:00Z"], "n": 1}]
