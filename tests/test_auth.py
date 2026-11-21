"""Authentication, authorisation and security headers."""

import pytest
from fastapi.testclient import TestClient

from app.audit import AuditLogger
from app.auth import UserStore
from app.auth.passwords import hash_password, password_problems, verify_password
from app.auth.policy import Principal, authorize
from app.core.evaluator import Evaluator
from app.escalation import EscalationQueue
from app.evidence.stubs import FixedSignal
from app.main import create_app

ADMIN = ("admin@example.com", "Adm1n-Passw0rd!")
VIEWER = ("viewer@example.com", "V1ewer-Passw0rd!")
PAYLOAD = {"query": "How many casual leaves?", "answer": "Employees get 18 casual leaves.",
           "evidence": [{"text": "Employees are entitled to 18 casual leaves."}],
           "profile": "standard", "time_sensitive": False}
ORIGIN = "http://localhost:8080"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_ADMIN_EMAIL", ADMIN[0])
    monkeypatch.setenv("AEGIS_ADMIN_PASSWORD", ADMIN[1])
    monkeypatch.setenv("AEGIS_API_KEYS", "test-service-key")
    monkeypatch.setenv("AEGIS_CORS_ORIGINS", ORIGIN)
    store = UserStore(str(tmp_path / "users.db"))
    evaluator = Evaluator([FixedSignal(n, v) for n, v in dict(
        relevance=0.95, entailment=0.95, contradiction=0.02, freshness=0.9,
        completeness=0.9, ambiguity=0.04).items()])
    application = create_app(evaluator, audit_logger=AuditLogger(str(tmp_path / "a.db")),
                             escalation_queue=EscalationQueue(str(tmp_path / "e.db")),
                             user_store=store, auth_enabled=True)
    store.create_user(*VIEWER, "viewer")
    return application


def signed_in(app, creds) -> TestClient:
    client = TestClient(app)
    r = client.post("/v1/auth/login", json={"email": creds[0], "password": creds[1]})
    assert r.status_code == 200, r.text
    return client


# ------------------------------------------------------------------ passwords
def test_password_hash_roundtrip_and_salt():
    a, b = hash_password("S3cret-pass!", iterations=1000), hash_password("S3cret-pass!", iterations=1000)
    assert a != b and verify_password("S3cret-pass!", a) and not verify_password("wrong", a)
    assert "S3cret" not in a


def test_password_policy():
    assert password_problems("Tester123$") == []
    assert password_problems("short") and password_problems("alllowercase1!")


# ----------------------------------------------------------- logged-out access
@pytest.mark.parametrize("method,path", [
    ("GET", "/v1/decisions"), ("GET", "/v1/escalations"), ("GET", "/v1/graph/status"),
    ("GET", "/v1/intelligence/summary"), ("GET", "/v1/config"), ("POST", "/v1/evaluate"),
    ("POST", "/v1/rag/ingest"), ("GET", "/v1/auth/users"), ("GET", "/v1/no-such-route"),
])
def test_signed_out_is_refused(app, method, path):
    r = TestClient(app).request(method, path, json={})
    assert r.status_code == 401


def test_health_stays_public(app):
    assert TestClient(app).get("/v1/health").status_code == 200


def test_me_requires_sign_in(app):
    assert TestClient(app).get("/v1/auth/me").status_code == 401


# --------------------------------------------------------------------- login
def test_login_sets_hardened_cookie_and_me_works(app):
    client = TestClient(app)
    r = client.post("/v1/auth/login", json={"email": ADMIN[0].upper(), "password": ADMIN[1]})
    assert r.status_code == 200 and r.json() == {"email": ADMIN[0], "role": "admin"}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=" in cookie
    assert ADMIN[1].lower() not in r.text.lower()
    assert client.get("/v1/auth/me").json()["role"] == "admin"


def test_wrong_password_and_unknown_user_look_identical(app):
    client = TestClient(app)
    a = client.post("/v1/auth/login", json={"email": ADMIN[0], "password": "nope"})
    b = client.post("/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_brute_force_is_rate_limited(app):
    client = TestClient(app)
    codes = [client.post("/v1/auth/login", json={"email": ADMIN[0], "password": f"bad{i}"}).status_code
             for i in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    # even the right password is refused while locked
    r = client.post("/v1/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    assert r.status_code == 429 and "retry-after" in r.headers


def test_logout_invalidates_the_session_server_side(app):
    client = signed_in(app, ADMIN)
    token = client.cookies.get("aegis_session")
    client.post("/v1/auth/logout")
    replay = TestClient(app)
    replay.cookies.set("aegis_session", token)
    assert replay.get("/v1/decisions").status_code == 401


def test_forged_session_cookie_is_refused(app):
    client = TestClient(app)
    client.cookies.set("aegis_session", "forged-token")
    assert client.get("/v1/decisions").status_code == 401


# --------------------------------------------------------------------- roles
def test_viewer_can_read_but_not_write(app):
    viewer = signed_in(app, VIEWER)
    assert viewer.get("/v1/decisions").status_code == 200
    assert viewer.post("/v1/evaluate", json=PAYLOAD).status_code == 403
    assert viewer.post("/v1/rag/ingest", json={"pdf_path": "x.pdf"}).status_code == 403
    assert viewer.patch("/v1/escalations/x", json={"status": "resolved"}).status_code == 403
    assert viewer.get("/v1/auth/users").status_code == 403
    assert viewer.post("/v1/auth/users", json={"email": "x@y.io", "password": "Aa1!aaaaaaaa",
                                              "role": "admin"}).status_code == 403


def test_admin_can_evaluate_and_manage_users(app):
    admin = signed_in(app, ADMIN)
    assert admin.post("/v1/evaluate", json=PAYLOAD).status_code == 200
    weak = admin.post("/v1/auth/users", json={"email": "r@example.com", "password": "weak",
                                             "role": "reviewer"})
    assert weak.status_code == 422
    ok = admin.post("/v1/auth/users", json={"email": "r@example.com", "password": "Rev1ewer-Pass!",
                                           "role": "reviewer"})
    assert ok.status_code == 201
    dup = admin.post("/v1/auth/users", json={"email": "R@example.com", "password": "Rev1ewer-Pass!",
                                            "role": "reviewer"})
    assert dup.status_code == 409
    assert "password" not in str(admin.get("/v1/auth/users").json()).lower()


def test_service_api_key_can_evaluate_but_not_read(app):
    client = TestClient(app)
    assert client.post("/v1/evaluate", json=PAYLOAD,
                       headers={"X-API-Key": "test-service-key"}).status_code == 200
    assert client.post("/v1/evaluate", json=PAYLOAD,
                       headers={"Authorization": "Bearer test-service-key"}).status_code == 200
    assert client.get("/v1/decisions", headers={"X-API-Key": "test-service-key"}).status_code == 403
    assert client.post("/v1/evaluate", json=PAYLOAD,
                       headers={"X-API-Key": "wrong"}).status_code == 401


def test_cookie_write_from_foreign_origin_is_refused(app):
    admin = signed_in(app, ADMIN)
    r = admin.post("/v1/evaluate", json=PAYLOAD, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert admin.post("/v1/evaluate", json=PAYLOAD, headers={"Origin": ORIGIN}).status_code == 200


# ------------------------------------------------------------- headers, CORS
def test_security_headers_on_api_responses(app):
    r = TestClient(app).get("/v1/health")
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"
    assert "referrer-policy" in h and "permissions-policy" in h


def test_cors_allows_only_configured_origin_with_credentials(app):
    client = TestClient(app)
    good = client.options("/v1/decisions", headers={"Origin": ORIGIN,
                                                    "Access-Control-Request-Method": "GET"})
    assert good.headers.get("access-control-allow-origin") == ORIGIN
    assert good.headers.get("access-control-allow-credentials") == "true"
    bad = client.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in bad.headers}


def test_auth_disabled_mode_reports_itself(tmp_path):
    evaluator = Evaluator([FixedSignal("relevance", 0.9)])
    client = TestClient(create_app(evaluator, auth_enabled=False))
    assert client.get("/v1/auth/me").json()["auth_enabled"] is False


def test_policy_defaults_to_admin_only_for_unknown_writes():
    viewer = Principal("user", "viewer", "v@example.com")
    assert authorize("POST", "/v1/something-new", viewer) == 403
    assert authorize("POST", "/v1/something-new", Principal("user", "admin")) == 0
    assert authorize("GET", "/docs", None) == 0
