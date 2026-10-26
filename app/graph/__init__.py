"""Decision Graph add-on: trace -> Neo4j.

The graph is a *secondary*, rebuildable store. Nothing in this package may
be called from inside the decision path: the SQLite audit log stays the
system of record, and a graph write that fails must leave the decision,
the response and the UI trace exactly as they were.

`safe_write_trace` is the only entry point an integration should call.
"""

from app.graph.contract import (
    CONFLICT_KINDS,
    NODE_TYPES,
    RELATIONSHIP_TYPES,
    EVIDENCE_PREVIEW_CHARS,
    TraceContractError,
    validate_trace,
)
from app.graph.sink import GraphSink, NullGraphSink, safe_write_trace

__all__ = [
    "CONFLICT_KINDS",
    "NODE_TYPES",
    "RELATIONSHIP_TYPES",
    "EVIDENCE_PREVIEW_CHARS",
    "TraceContractError",
    "validate_trace",
    "GraphSink",
    "NullGraphSink",
    "safe_write_trace",
]
