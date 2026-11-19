"""AsyncGraphSink: graph writes must neither fail nor delay a decision."""

from __future__ import annotations

import threading
import time

import pytest

from app.graph.async_sink import AsyncGraphSink
from app.graph.neo4j_sink import Neo4jGraphSink
from app.graph.sink import safe_write_trace
from tests.graph.fake_driver import FakeDriver, FakeGraph


def _trace(n: int = 0):
    return {
        "request_id": f"r-{n}",
        "decision": "ANSWER",
        "nodes": [{"id": f"r-{n}", "type": "Decision", "decision": "ANSWER"}],
        "edges": [],
    }


class RecordingSink:
    def __init__(self, result=True):
        self.traces = []
        self.result = result
        self.closed = False
        self.last_error = None

    def write_trace(self, trace):
        self.traces.append(trace)
        if not self.result:
            self.last_error = "simulated refusal"
        return self.result

    def close(self):
        self.closed = True


class GatedSink(RecordingSink):
    """Blocks inside write_trace until `release` is set."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def write_trace(self, trace):
        self.entered.set()
        self.release.wait(timeout=10)
        return super().write_trace(trace)


class ExplodingSink:
    def write_trace(self, trace):
        raise RuntimeError("Neo4j is down")


@pytest.fixture
def make_sink():
    created = []

    def _make(inner, **kwargs):
        sink = AsyncGraphSink(inner, register_atexit=False, **kwargs)
        created.append((sink, inner))
        return sink

    yield _make
    for sink, inner in created:
        release = getattr(inner, "release", None)
        if release is not None:
            release.set()
        sink.close(timeout=2)


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------
def test_traces_are_written_in_the_background_in_order(make_sink):
    inner = RecordingSink()
    sink = make_sink(inner)

    for n in range(5):
        assert sink.write_trace(_trace(n)) is True
    assert sink.flush(timeout=5) is True

    assert [t["request_id"] for t in inner.traces] == [f"r-{n}" for n in range(5)]
    stats = sink.stats()
    assert stats["written"] == 5
    assert stats["failed"] == stats["dropped"] == stats["pending"] == 0
    assert stats["last_error"] is None
    assert stats["last_success_at"]
    assert stats["queue_capacity"] == 256
    assert stats["running"] is True


def test_stats_have_every_contract_field(make_sink):
    stats = make_sink(RecordingSink()).stats()
    assert {"written", "failed", "dropped", "pending", "last_error", "last_success_at"} <= set(stats)
    assert stats["running"] is False, "the worker starts lazily"


def test_write_does_not_block_on_a_slow_store(make_sink):
    inner = GatedSink()
    sink = make_sink(inner)

    started = time.perf_counter()
    assert sink.write_trace(_trace(0)) is True
    assert sink.write_trace(_trace(1)) is True
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, "queueing must not wait for the store"
    assert inner.entered.wait(timeout=5)
    assert sink.stats()["pending"] == 2
    assert sink.flush(timeout=0.05) is False, "flush reports a timeout honestly"

    inner.release.set()
    assert sink.flush(timeout=5) is True
    assert sink.stats()["written"] == 2


def test_the_queued_trace_is_a_copy(make_sink):
    inner = GatedSink()
    sink = make_sink(inner)
    blocker, trace = _trace(0), _trace(1)
    sink.write_trace(blocker)
    sink.write_trace(trace)
    trace["nodes"].append({"id": "late", "type": "Claim"})  # caller mutates afterwards

    inner.release.set()
    sink.flush(timeout=5)
    assert len(inner.traces[1]["nodes"]) == 1


def test_it_works_through_safe_write_trace_with_a_real_sink(make_sink):
    driver = FakeDriver()
    sink = make_sink(Neo4jGraphSink(driver))
    assert safe_write_trace(sink, _trace(7)) is True
    assert sink.flush(timeout=5) is True
    assert len(FakeGraph.from_driver(driver).labels("Decision")) == 1


# ---------------------------------------------------------------------------
# failure
# ---------------------------------------------------------------------------
def test_a_refused_write_is_counted_not_raised(make_sink):
    sink = make_sink(RecordingSink(result=False))
    assert sink.write_trace(_trace()) is True  # accepted; the failure is asynchronous
    sink.flush(timeout=5)

    stats = sink.stats()
    assert stats["failed"] == 1 and stats["written"] == 0
    assert stats["last_error"] == "simulated refusal"
    assert stats["last_success_at"] is None


def test_an_exploding_store_does_not_kill_the_worker(make_sink):
    sink = make_sink(ExplodingSink())
    for n in range(3):
        sink.write_trace(_trace(n))
    assert sink.flush(timeout=5) is True

    stats = sink.stats()
    assert stats["failed"] == 3
    assert stats["running"] is True
    assert stats["last_error"]


def test_a_dead_neo4j_fails_in_the_background(make_sink):
    sink = make_sink(Neo4jGraphSink(FakeDriver(fail_on_session=True)))
    assert sink.write_trace(_trace()) is True
    sink.flush(timeout=5)
    stats = sink.stats()
    assert stats["failed"] == 1
    assert "cannot open a session" in stats["last_error"]


def test_recovery_after_failure_updates_last_success(make_sink):
    inner = RecordingSink(result=False)
    sink = make_sink(inner)
    sink.write_trace(_trace(0))
    sink.flush(timeout=5)
    inner.result = True
    sink.write_trace(_trace(1))
    sink.flush(timeout=5)

    stats = sink.stats()
    assert (stats["failed"], stats["written"]) == (1, 1)
    assert stats["last_success_at"]


def test_an_uncopyable_trace_is_a_counted_failure(make_sink):
    sink = make_sink(RecordingSink())
    assert sink.write_trace({"request_id": "r", "lock": threading.Lock()}) is False
    assert sink.stats()["failed"] == 1


# ---------------------------------------------------------------------------
# backpressure
# ---------------------------------------------------------------------------
def test_drop_oldest_keeps_the_newest_traces(make_sink):
    inner = GatedSink()
    sink = make_sink(inner, max_queue=2)

    sink.write_trace(_trace(0))
    assert inner.entered.wait(timeout=5)  # r-0 is in flight, queue is empty
    for n in range(1, 6):  # r-1..r-5 into a queue of 2
        assert sink.write_trace(_trace(n)) is True

    assert sink.stats()["dropped"] == 3
    assert sink.stats()["pending"] == 3

    inner.release.set()
    assert sink.flush(timeout=5) is True
    assert [t["request_id"] for t in inner.traces] == ["r-0", "r-4", "r-5"]
    assert sink.stats()["written"] == 3


def test_drop_new_keeps_the_oldest_traces(make_sink):
    inner = GatedSink()
    sink = make_sink(inner, max_queue=2, overflow="drop_new")

    sink.write_trace(_trace(0))
    assert inner.entered.wait(timeout=5)
    results = [sink.write_trace(_trace(n)) for n in range(1, 6)]

    assert results == [True, True, False, False, False]
    assert sink.stats()["dropped"] == 3

    inner.release.set()
    sink.flush(timeout=5)
    assert [t["request_id"] for t in inner.traces] == ["r-0", "r-1", "r-2"]


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError):
        AsyncGraphSink(None, register_atexit=False)
    with pytest.raises(ValueError):
        AsyncGraphSink(RecordingSink(), max_queue=0, register_atexit=False)
    with pytest.raises(ValueError):
        AsyncGraphSink(RecordingSink(), overflow="block", register_atexit=False)


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------
def test_close_drains_stops_the_worker_and_closes_the_store():
    inner = RecordingSink()
    sink = AsyncGraphSink(inner, register_atexit=False)
    for n in range(4):
        sink.write_trace(_trace(n))

    assert sink.close(timeout=5) is True
    assert len(inner.traces) == 4, "close drains what was accepted"
    assert inner.closed is True
    assert sink.stats()["running"] is False

    assert sink.write_trace(_trace(99)) is False, "a closed writer accepts nothing"
    assert sink.stats()["dropped"] == 1
    assert sink.close(timeout=1) is True, "close is idempotent"


def test_close_gives_up_on_a_hung_store_and_counts_the_loss():
    inner = GatedSink()
    sink = AsyncGraphSink(inner, register_atexit=False)
    sink.write_trace(_trace(0))
    assert inner.entered.wait(timeout=5)
    sink.write_trace(_trace(1))
    sink.write_trace(_trace(2))

    assert sink.close(timeout=0.1) is False
    assert sink.stats()["dropped"] == 2
    inner.release.set()


def test_closing_without_ever_writing_is_fine():
    inner = RecordingSink()
    assert AsyncGraphSink(inner, register_atexit=False).close(timeout=1) is True
    assert inner.closed is True
