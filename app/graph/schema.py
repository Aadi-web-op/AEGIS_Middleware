"""Neo4j schema definitions: constraints and indexes for the Aegis Decision Graph.

Implements constraints and indexes defined in "Aegis Decision Graph (Neo4j Add-on): Team Brief".
Ensures idempotent schema setup using `IF NOT EXISTS`.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

CONSTRAINTS: List[str] = [
    # A Decision is identified by request_id alone (Rule 3)
    "CREATE CONSTRAINT decision_request_id IF NOT EXISTS FOR (d:Decision) REQUIRE d.request_id IS UNIQUE",
    # Claims are unique by id
    "CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE",
    # Evidence chunks are unique by id
    "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:Evidence) REQUIRE e.id IS UNIQUE",
    # Documents are globally unique: doc:<source>@<version>
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
    # Reasons are unique by id
    "CREATE CONSTRAINT reason_id IF NOT EXISTS FOR (r:Reason) REQUIRE r.id IS UNIQUE",
]

INDEXES: List[str] = [
    # Fast matching on Decision id for edges
    "CREATE INDEX decision_id IF NOT EXISTS FOR (d:Decision) ON (d.id)",
    # Fast filtering by decision outcome
    "CREATE INDEX decision_decision IF NOT EXISTS FOR (d:Decision) ON (d.decision)",
    # Document source lookup for conflict & impact queries
    "CREATE INDEX document_source IF NOT EXISTS FOR (d:Document) ON (d.source)",
    "CREATE INDEX document_version IF NOT EXISTS FOR (d:Document) ON (d.version)",
    # Reason code lookup for root cause analysis
    "CREATE INDEX reason_code IF NOT EXISTS FOR (r:Reason) ON (r.code)",
    # Relationship property index for conflict kinds
    "CREATE INDEX conflicts_with_kind IF NOT EXISTS FOR ()-[r:CONFLICTS_WITH]-() ON (r.kind)",
]

ALL_SCHEMA_STATEMENTS: List[str] = CONSTRAINTS + INDEXES


def apply_schema(driver: Any, database: Optional[str] = None) -> List[str]:
    """Execute all schema constraints and indexes against the given Neo4j driver.

    Args:
        driver: A Neo4j driver instance or compatible fake driver.
        database: Optional Neo4j database name.

    Returns:
        The list of executed Cypher statements.
    """
    executed: List[str] = []

    def _execute_statements(tx: Any) -> None:
        for stmt in ALL_SCHEMA_STATEMENTS:
            tx.run(stmt)
            executed.append(stmt)

    session_kwargs = {"database": database} if database else {}
    with driver.session(**session_kwargs) as session:
        if hasattr(session, "execute_write"):
            session.execute_write(_execute_statements)
        else:
            for stmt in ALL_SCHEMA_STATEMENTS:
                session.run(stmt)
                executed.append(stmt)

    logger.info("Successfully applied %d Neo4j schema statements", len(executed))
    return executed
