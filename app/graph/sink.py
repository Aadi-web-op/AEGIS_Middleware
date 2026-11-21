"""Graph sink interface and the failure isolation around it.

The one rule this module exists to enforce: a graph write can fail in any
way at all -- a dead server, a bad trace, a driver that raises on import --
and the decision, the response and the UI trace are unaffected.

`safe_write_trace` is therefore the only function an integration should
call. It returns a bool and never raises.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class GraphSink(Protocol):
    """Something that can persist a decision trace to a graph store."""

    def write_trace(self, trace: Mapping[str, Any]) -> bool:
        """Persist `trace`. Return True on success, False on failure.

        Implementations should not raise; `safe_write_trace` guards
        against the ones that do anyway.
        """
        ...


class NullGraphSink:
    """A sink that accepts and discards. The default when Neo4j is absent."""

    def __init__(self) -> None:
        self.written: int = 0

    def write_trace(self, trace: Mapping[str, Any]) -> bool:
        self.written += 1
        logger.debug(
            "NullGraphSink discarded trace %s", _request_id(trace)
        )
        return True


def _request_id(trace: Any) -> str:
    """Best-effort request id for a log line, even from a malformed trace."""
    try:
        value = trace.get("request_id")
    except AttributeError:
        return "<unreadable>"
    return value if isinstance(value, str) and value else "<missing>"


def safe_write_trace(
    sink: Optional[GraphSink], trace: Mapping[str, Any]
) -> bool:
    """Write `trace` to `sink`, swallowing and logging every failure.

    Returns True only when the sink reported success. A missing sink, a
    malformed trace, a driver exception and a sink that itself raises all
    return False after logging -- never an exception to the caller, which
    is what keeps Neo4j out of the decision path.
    """
    if sink is None:
        logger.debug("No graph sink configured; skipping trace %s", _request_id(trace))
        return False

    try:
        wrote = sink.write_trace(trace)
    except Exception:
        # Deliberately broad: the contract with the decision path is that
        # nothing escapes here, including errors from a driver we do not
        # control. The traceback is logged so a failed write is diagnosable.
        logger.exception(
            "Graph write failed for request %s; decision and trace are unaffected",
            _request_id(trace),
        )
        return False

    if not wrote:
        logger.warning(
            "Graph sink %s reported a failed write for request %s; "
            "decision and trace are unaffected",
            type(sink).__name__,
            _request_id(trace),
        )
    return bool(wrote)
