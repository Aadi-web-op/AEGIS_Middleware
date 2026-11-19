"""AsyncGraphSink: graph writes off the decision path.

`safe_write_trace` already guarantees a graph write cannot *fail* a
decision. This module guarantees it cannot *delay* one either: a slow or
dead Neo4j costs `evaluate()` a queue insert, nothing more.

Design
------
* `write_trace` deep-copies the trace and puts it on a bounded in-memory
  queue. It never blocks and never raises. It returns True when the trace
  was accepted for writing (not when it has been written).
* One daemon thread drains the queue through `safe_write_trace(inner, ...)`,
  so every existing failure-isolation rule still applies to the real write.
* The queue is bounded. When it is full the configured overflow policy
  applies -- `"drop_oldest"` (default: the newest decisions are the ones a
  user is looking at) or `"drop_new"` -- and the loss is counted in
  `dropped`. Nothing is lost for good: the graph is a projection of the
  audit log and `scripts/rebuild_graph.py` replays it.
* `stats()` exposes written / failed / dropped / pending / last_error /
  last_success_at for `/v1/graph/status`.
* `flush(timeout)` blocks until everything accepted so far has been
  attempted; `close(timeout)` drains, stops the worker and closes the
  wrapped sink.
"""

from __future__ import annotations

import atexit
import copy
import datetime
import logging
import threading
from collections import deque
from typing import Any, Deque, Dict, Mapping, Optional

from app.graph.sink import GraphSink, safe_write_trace

logger = logging.getLogger(__name__)

DEFAULT_MAX_QUEUE = 256
OVERFLOW_POLICIES = ("drop_oldest", "drop_new")


class AsyncGraphSink:
    """Wraps a `GraphSink` with a bounded background writer."""

    def __init__(
        self,
        inner: GraphSink,
        max_queue: int = DEFAULT_MAX_QUEUE,
        overflow: str = "drop_oldest",
        name: str = "aegis-graph-writer",
        register_atexit: bool = True,
    ) -> None:
        if inner is None:
            raise ValueError("AsyncGraphSink requires a sink to wrap")
        if max_queue < 1:
            raise ValueError("max_queue must be at least 1")
        if overflow not in OVERFLOW_POLICIES:
            raise ValueError(f"overflow must be one of {OVERFLOW_POLICIES}")

        self._inner = inner
        self._max_queue = max_queue
        self._overflow = overflow
        self._name = name

        self._cond = threading.Condition()
        self._queue: Deque[Mapping[str, Any]] = deque()
        self._in_flight = 0
        self._closed = False
        self._thread: Optional[threading.Thread] = None

        self._written = 0
        self._failed = 0
        self._dropped = 0
        self._last_error: Optional[str] = None
        self._last_success_at: Optional[str] = None

        if register_atexit:
            atexit.register(self.close, 2.0)

    # ------------------------------------------------------------------
    @property
    def inner(self) -> GraphSink:
        return self._inner

    def write_trace(self, trace: Mapping[str, Any]) -> bool:
        """Queue `trace` for writing. Never blocks, never raises."""
        try:
            # The caller goes on to return this same dict in the response;
            # copying keeps the worker's view stable whatever happens to it.
            item = copy.deepcopy(trace)
        except Exception as exc:
            with self._cond:
                self._failed += 1
                self._last_error = f"could not copy trace: {type(exc).__name__}: {exc}"
            logger.exception("Could not queue a trace for the graph writer")
            return False

        with self._cond:
            if self._closed:
                self._dropped += 1
                self._last_error = "graph writer is closed"
                return False
            if len(self._queue) >= self._max_queue:
                self._dropped += 1
                if self._overflow == "drop_new":
                    logger.warning(
                        "Graph write queue is full (%d); dropping the new trace",
                        self._max_queue,
                    )
                    return False
                self._queue.popleft()
                logger.warning(
                    "Graph write queue is full (%d); dropped the oldest trace",
                    self._max_queue,
                )
            self._queue.append(item)
            self._ensure_worker()
            self._cond.notify_all()
        return True

    # ------------------------------------------------------------------
    def _ensure_worker(self) -> None:
        """Start the worker if it is not running. Caller holds the lock."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._closed:
                    self._cond.wait()
                if not self._queue:  # closed and drained
                    return
                item = self._queue.popleft()
                self._in_flight += 1

            ok = False
            error: Optional[str] = None
            try:
                ok = safe_write_trace(self._inner, item)
                if not ok:
                    error = getattr(self._inner, "last_error", None) or "graph write failed"
            except BaseException as exc:  # safe_write_trace should make this unreachable
                error = f"{type(exc).__name__}: {exc}"
                logger.exception("Graph writer thread caught an unexpected error")

            with self._cond:
                self._in_flight -= 1
                if ok:
                    self._written += 1
                    self._last_success_at = datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(timespec="milliseconds")
                else:
                    self._failed += 1
                    self._last_error = str(error)
                self._cond.notify_all()

    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        """A snapshot of the writer's counters."""
        with self._cond:
            return {
                "written": self._written,
                "failed": self._failed,
                "dropped": self._dropped,
                "pending": len(self._queue) + self._in_flight,
                "last_error": self._last_error,
                "last_success_at": self._last_success_at,
                "queue_capacity": self._max_queue,
                "running": bool(self._thread is not None and self._thread.is_alive()),
            }

    @property
    def last_error(self) -> Optional[str]:
        with self._cond:
            return self._last_error

    def flush(self, timeout: Optional[float] = 5.0) -> bool:
        """Wait until every accepted trace has been attempted.

        Returns True when the queue drained, False on timeout.
        """
        with self._cond:
            return self._cond.wait_for(
                lambda: not self._queue and self._in_flight == 0, timeout=timeout
            )

    def close(self, timeout: Optional[float] = 5.0) -> bool:
        """Drain (up to `timeout`), stop the worker, close the wrapped sink.

        Idempotent. Returns True when the worker stopped in time. Traces
        still queued after the timeout are counted as dropped.
        """
        with self._cond:
            already_closed = self._closed
            self._closed = True
            self._cond.notify_all()
            thread = self._thread

        stopped = True
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
            stopped = not thread.is_alive()

        if not stopped:
            with self._cond:
                abandoned = len(self._queue)
                self._queue.clear()
                self._dropped += abandoned
                self._cond.notify_all()
            logger.warning(
                "Graph writer did not stop within %ss; %d queued trace(s) dropped",
                timeout,
                abandoned,
            )

        if not already_closed:
            closer = getattr(self._inner, "close", None)
            if callable(closer) and stopped:
                try:
                    closer()
                except Exception:
                    logger.exception("Closing the wrapped graph sink failed")
        return stopped
