"""Mirror locked facts into the Neo4j decision graph (best effort).

    (:Fact {id: "fact:<key>@<row id>"})-[:SUPERSEDES]->(:Fact)   version history
    (:Fact)-[:DEFINED_IN]->(:Document {source, version})        when that document exists
    (:Decision)-[:ASSERTS {verdict, stated}]->(:Fact)            what an answer claimed

SQLite stays the system of record; failures here are logged and ignored,
exactly like the decision-trace writer.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable

from app.facts.store import Fact

logger = logging.getLogger(__name__)

_UPSERT_FACT = """
MERGE (f:Fact {id: $id})
SET f.key = $key, f.label = $label, f.kind = $kind, f.value = $value, f.level = $level,
    f.source = $source, f.version = $version, f.status = $status
WITH f
OPTIONAL MATCH (doc:Document {source: $source, version: $version})
FOREACH (_ IN CASE WHEN doc IS NULL THEN [] ELSE [1] END | MERGE (f)-[:DEFINED_IN]->(doc))
"""
_SUPERSEDE = """
MATCH (new:Fact {id: $new_id}), (old:Fact {id: $old_id})
SET old.status = 'superseded'
MERGE (new)-[:SUPERSEDES]->(old)
"""
_ASSERTS = """
MERGE (d:Decision {request_id: $request_id})
WITH d
MATCH (f:Fact {id: $fact_id})
MERGE (d)-[r:ASSERTS]->(f)
SET r.verdict = $verdict, r.stated = $stated, r.level = $level
"""


def fact_node_id(fact: Fact) -> str:
    return f"fact:{fact.key}@{fact.id}"


class FactGraph:
    def __init__(self, driver: Any | None, database: str | None = None):
        self.driver = driver
        self.database = database
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fact-graph")

    def _submit(self, statements: list[tuple[str, dict]]) -> None:
        if self.driver is None:
            return

        def run() -> None:
            try:
                with self.driver.session(database=self.database) as session:
                    for cypher, params in statements:
                        session.run(cypher, params).consume()
            except Exception as exc:  # never let the graph break the API
                logger.warning("Fact graph write failed: %s", exc)

        self._pool.submit(run)

    @staticmethod
    def _params(fact: Fact) -> dict:
        return {"id": fact_node_id(fact), "key": fact.key, "label": fact.label, "kind": fact.kind,
                "value": fact.value, "level": fact.level, "source": fact.source,
                "version": fact.version, "status": fact.status}

    def upsert(self, fact: Fact, supersedes: Fact | None = None) -> None:
        statements = [(_UPSERT_FACT, self._params(fact))]
        if supersedes is not None:
            statements.append((_UPSERT_FACT, self._params(supersedes)))
            statements.append((_SUPERSEDE, {"new_id": fact_node_id(fact),
                                            "old_id": fact_node_id(supersedes)}))
        self._submit(statements)

    def record(self, request_id: str, checks: Iterable[Any], facts: dict[str, Fact]) -> None:
        statements = []
        for check in checks:
            fact = facts.get(check.fact_key)
            if fact is None or check.verdict == "not_stated":
                continue
            statements.append((_UPSERT_FACT, self._params(fact)))
            statements.append((_ASSERTS, {"request_id": request_id, "fact_id": fact_node_id(fact),
                                          "verdict": check.verdict, "stated": check.stated,
                                          "level": check.level}))
        if statements:
            self._submit(statements)
