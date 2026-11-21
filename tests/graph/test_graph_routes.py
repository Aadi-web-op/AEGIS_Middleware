"""`/v1/graph/*` routes: availability behaviour and response shapes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.graph import routes as graph_routes
from app.graph.async_sink import AsyncGraphSink
from app.graph.contract import NODE_TYPES, RELATIONSHIP_TYPES
from app.graph.routes import router
from tests.graph.fake_driver import FakeReadDriver
from tests.graph.test_reader import _responder

GRAPH_ENDPOINTS = [
    "/v1/graph/decisions",
    "/v1/graph/decisions/r1",
    "/v1/graph/documents",
    "/v1/graph/nodes/doc%3Ahr.pdf%40v1/neighbors",
]


def _client(driver=None, evaluator=None) -> TestClient:
    app = FastAPI()
    app.state.neo4j_driver = driver
    app.state.evaluator = evaluator
    app.include_router(router)
    return TestClient(app)


class _Evaluator:
    def __init__(self, sink):
        self.graph_sink = sink


# ---------------------------------------------------------------------------
# unavailable
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", GRAPH_ENDPOINTS)
def test_no_driver_is_503_with_graph_available_false(path):
    response = _client(driver=None).get(path)
    assert response.status_code == 503
    body = response.json()
    assert body["graph_available"] is False
    assert "not configured" in body["detail"]


@pytest.mark.parametrize("path", GRAPH_ENDPOINTS)
def test_unreachable_neo4j_is_503_without_leaking_internals(path):
    response = _client(driver=FakeReadDriver(fail=True)).get(path)
    assert response.status_code == 503
    body = response.json()
    assert body["graph_available"] is False
    assert "fake driver" not in body["detail"]
    assert "Traceback" not in response.text


def test_a_failure_is_remembered_briefly_so_polling_fails_fast():
    calls = {"n": 0}

    def failing(cypher, params):
        calls["n"] += 1
        raise RuntimeError("down")

    client = _client(driver=FakeReadDriver(failing))
    assert client.get("/v1/graph/documents").status_code == 503
    assert client.get("/v1/graph/documents").status_code == 503
    assert client.get("/v1/graph/status").json()["connected"] is False
    assert calls["n"] == 1, "the second and third requests did not hit the driver"


def test_the_down_marker_expires(monkeypatch):
    state = {"fail": True}

    def flaky(cypher, params):
        if state["fail"]:
            raise RuntimeError("down")
        return _responder(cypher, params)

    monkeypatch.setattr(graph_routes, "DOWN_TTL_SECONDS", 0.0)
    client = _client(driver=FakeReadDriver(flaky))
    assert client.get("/v1/graph/documents").status_code == 503
    state["fail"] = False
    assert client.get("/v1/graph/documents").status_code == 200


# ---------------------------------------------------------------------------
# status: always 200
# ---------------------------------------------------------------------------
def test_status_without_a_driver():
    response = _client(driver=None).get("/v1/graph/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False and body["connected"] is False
    assert body["counts"] == {} and body["relationships"] == {}
    assert body["writer"] == {
        "written": 0, "failed": 0, "dropped": 0, "pending": 0,
        "last_error": None, "last_success_at": None,
    }


def test_status_with_an_unreachable_server():
    response = _client(driver=FakeReadDriver(fail=True)).get("/v1/graph/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True and body["connected"] is False


def test_status_when_connected_reports_counts_and_writer():
    class _Sink:
        def write_trace(self, trace):
            return True

    writer = AsyncGraphSink(_Sink(), register_atexit=False)
    try:
        writer.write_trace({"request_id": "r"})
        writer.flush(timeout=5)
        client = _client(driver=FakeReadDriver(_responder), evaluator=_Evaluator(writer))
        body = client.get("/v1/graph/status").json()
    finally:
        writer.close(timeout=2)

    assert body["configured"] is True and body["connected"] is True
    assert set(body["counts"]) == set(NODE_TYPES)
    assert set(body["relationships"]) == set(RELATIONSHIP_TYPES)
    assert body["writer"]["written"] == 1
    assert body["writer"]["pending"] == 0
    assert body["writer"]["queue_capacity"] == 256


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    return _client(driver=FakeReadDriver(_responder))


def test_decisions_list(client):
    response = client.get("/v1/graph/decisions?limit=5&decision=escalate&source=hr.pdf")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["request_id"] == "r1"
    assert items[0]["reason_codes"] == ["CONTRADICTION"]


def test_decisions_list_validates_its_parameters(client):
    assert client.get("/v1/graph/decisions?decision=MAYBE").status_code == 422
    assert client.get("/v1/graph/decisions?limit=0").status_code == 422
    assert client.get("/v1/graph/decisions?limit=100000").status_code == 422


def test_decision_subgraph(client):
    response = client.get("/v1/graph/decisions/r1")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"decision", "nodes", "edges"}
    assert body["decision"]["request_id"] == "r1"
    assert {n["type"] for n in body["nodes"]} == set(NODE_TYPES)


def test_decision_subgraph_404(client):
    response = client.get("/v1/graph/decisions/absent")
    assert response.status_code == 404
    assert "graph_available" not in response.json()


def test_documents(client):
    response = client.get("/v1/graph/documents?limit=10")
    assert response.status_code == 200
    item = response.json()["items"][0]
    for key in ("doc_id", "source", "version", "date", "decision_count",
                "supported_claim_count", "contradicted_claim_count",
                "conflict_count", "superseded_by", "supersedes"):
        assert key in item


def test_neighbors_accepts_url_encoded_and_raw_ids(client):
    for path in (
        "/v1/graph/nodes/doc%3Ahr.pdf%40v1/neighbors",
        "/v1/graph/nodes/doc:hr.pdf@v1/neighbors?limit=5",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.json()
        assert body["center"] == "doc:hr.pdf@v1"
        assert len(body["nodes"]) == 2 and len(body["edges"]) == 1


def test_neighbors_404(client):
    assert client.get("/v1/graph/nodes/absent/neighbors").status_code == 404


def test_the_router_is_mounted_in_the_real_app():
    from app.main import create_app
    from tests.graph.test_trace_v2 import _evaluator

    app = create_app(evaluator=_evaluator(None))
    with TestClient(app) as real:
        status = real.get("/v1/graph/status")
        assert status.status_code == 200
        assert status.json()["configured"] is False
        assert real.get("/v1/graph/decisions").status_code == 503
