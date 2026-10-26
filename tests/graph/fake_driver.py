"""A fake Neo4j driver.

Mimics only what `Neo4jGraphSink` uses -- `driver.session()` as a context
manager, `session.execute_write(fn, *args)`, and `tx.run(cypher, **params)`
-- and records every statement so tests can assert on the generated Cypher
and its parameters. No server, no `neo4j` package, no network.

`FakeGraph` additionally replays the recorded MERGE statements into an
in-memory graph, which is how the idempotency tests check that writing a
trace twice leaves one copy of everything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class Call:
    """One recorded `tx.run(...)`."""
    cypher: str
    params: Dict[str, Any]

    @property
    def is_node_merge(self) -> bool:
        return self.cypher.startswith("MERGE (n:")

    @property
    def label(self) -> Optional[str]:
        match = re.match(r"MERGE \(n:(\w+) ", self.cypher)
        return match.group(1) if match else None

    @property
    def relationship(self) -> Optional[str]:
        match = re.search(r"MERGE \(a\)-\[r:(\w+)", self.cypher)
        return match.group(1) if match else None


class FakeTransaction:
    def __init__(self, calls: List[Call], fail_on: Optional[Callable[[str], bool]]):
        self._calls = calls
        self._fail_on = fail_on

    def run(self, cypher: str, **params: Any) -> None:
        if self._fail_on is not None and self._fail_on(cypher):
            raise RuntimeError("fake driver: simulated Neo4j failure")
        self._calls.append(Call(cypher, dict(params)))


class FakeSession:
    def __init__(
        self,
        driver: "FakeDriver",
        database: Optional[str] = None,
    ):
        self._driver = driver
        self.database = database
        driver.sessions.append(self)
        self.closed = False

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        self.closed = True
        return False

    def execute_write(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        # A real driver runs the unit of work in a transaction and commits
        # only if it returns; recording into a staging list and extending
        # on success reproduces that all-or-nothing behaviour.
        staged: List[Call] = []
        tx = FakeTransaction(staged, self._driver.fail_on)
        result = fn(tx, *args, **kwargs)
        self._driver.calls.extend(staged)
        self._driver.transactions += 1
        return result


class FakeDriver:
    """Records statements. `fail_on` makes a matching statement raise."""

    def __init__(
        self,
        fail_on: Optional[Callable[[str], bool]] = None,
        fail_on_session: bool = False,
    ):
        self.calls: List[Call] = []
        self.sessions: List[FakeSession] = []
        self.transactions = 0
        self.fail_on = fail_on
        self.fail_on_session = fail_on_session
        self.closed = False

    def session(self, **kwargs: Any) -> FakeSession:
        if self.fail_on_session:
            raise RuntimeError("fake driver: cannot open a session")
        return FakeSession(self, database=kwargs.get("database"))

    def close(self) -> None:
        self.closed = True

    # -- convenience for assertions ------------------------------------
    def node_merges(self, label: Optional[str] = None) -> List[Call]:
        calls = [c for c in self.calls if c.is_node_merge]
        return [c for c in calls if c.label == label] if label else calls

    def edge_merges(self, relationship: Optional[str] = None) -> List[Call]:
        calls = [c for c in self.calls if c.relationship]
        return (
            [c for c in calls if c.relationship == relationship]
            if relationship
            else calls
        )

    def node_props(self, label: str) -> List[Dict[str, Any]]:
        return [c.params["props"] for c in self.node_merges(label)]


@dataclass
class FakeGraph:
    """Replays recorded statements into an in-memory graph."""

    nodes: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)
    edges: Dict[Tuple[str, str, str, Any], Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_driver(cls, driver: FakeDriver) -> "FakeGraph":
        graph = cls()
        for call in driver.calls:
            if call.is_node_merge:
                key = (call.label or "", str(call.params["merge_key"]))
                graph.nodes.setdefault(key, {}).update(call.params["props"])
            elif call.relationship:
                key = (
                    str(call.params["from_id"]),
                    call.relationship,
                    str(call.params["to_id"]),
                    call.params.get("kind"),
                )
                graph.edges.setdefault(key, {}).update(call.params["props"])
        return graph

    def labels(self, label: str) -> List[Dict[str, Any]]:
        return [props for (lbl, _), props in self.nodes.items() if lbl == label]

    def relationships(self, relationship: str) -> List[Tuple[str, str, Any]]:
        return [
            (start, end, kind)
            for (start, rel, end, kind) in self.edges
            if rel == relationship
        ]
