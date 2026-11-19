"""Neo4j driver construction with timeouts suited to an optional store.

The graph is a secondary projection: when Neo4j is slow or down, callers
must find out in seconds, not after the driver's default 30-second
transaction retry window. Every place that builds a real driver goes
through `make_driver` so the timeouts are the same everywhere.
"""

from __future__ import annotations

from typing import Any

# Seconds.
CONNECTION_TIMEOUT = 3.0
CONNECTION_ACQUISITION_TIMEOUT = 5.0
MAX_TRANSACTION_RETRY_TIME = 5.0


def make_driver(uri: str, user: str, password: str, **overrides: Any) -> Any:
    """Build a Neo4j driver with short timeouts.

    The driver connects lazily, so this succeeds even when the server is
    down; the first query is what fails (quickly). `neo4j` is imported
    here so the package stays optional.
    """
    from neo4j import GraphDatabase

    options: dict[str, Any] = {
        "connection_timeout": CONNECTION_TIMEOUT,
        "connection_acquisition_timeout": CONNECTION_ACQUISITION_TIMEOUT,
        "max_transaction_retry_time": MAX_TRANSACTION_RETRY_TIME,
    }
    options.update(overrides)
    return GraphDatabase.driver(uri, auth=(user, password), **options)
