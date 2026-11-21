"""Fact Lock: locked facts are checked deterministically, whatever retrieval returned."""

import pytest
from fastapi.testclient import TestClient

from app.audit import AuditLogger
from app.auth import UserStore
from app.core.evaluator import Evaluator
from app.escalation import EscalationQueue
from app.evidence.stubs import FixedSignal
from app.facts import Fact, FactLock, FactStore
from app.facts.values import extract_values, parse_value
from app.main import create_app
from app.schemas import Decision, EvaluateRequest, EvidenceItem, ReasonCode

GOOD = dict(relevance=0.95, entailment=0.95, contradiction=0.02,
            freshness=0.9, completeness=0.9, ambiguity=0.04)
PRIVACY = "LEGAL_Data_Privacy_Policy.pdf"


def facts_store() -> FactStore:
    store = FactStore(":memory:")
    for fact in [
        Fact(key="refund_window", label="refund window", kind="duration", value="15 days",
             level=3, aliases=["return window", "return order"], source="Refund_Policy.pdf",
             version="2026"),
        Fact(key="casual_leave", label="casual leave", kind="duration", value="12 days",
             level=2, source="HR_Leave_Policy.pdf", version="2026"),
        Fact(key="hotel_limit_metro", label="hotel limit metro", kind="money", value="Rs 7,500",
             level=3, source="FIN_Circular.pdf", version="FIN/2026/07"),
        Fact(key="hotel_limit_other", label="hotel limit other cities", kind="money",
             value="Rs 4,000", level=1),
        Fact(key="data_request_days", label="personal data request response", kind="duration",
             value="30 days", level=4, aliases=["delete personal data", "access personal data"],
             source=PRIVACY, version="2.0"),
    ]:
        store.create(fact)
    return store


@pytest.fixture
def lock():
    return FactLock(facts_store())


def by_key(result):
    return {c.fact_key: c for c in result.checks}


# ------------------------------------------------------------------ values
@pytest.mark.parametrize("text,kind,amount,unit", [
    ("Rs 7,500", "money", 7500, "INR"),
    ("₹5 lakh", "money", 500000, "INR"),
    ("INR 1,00,000", "money", 100000, "INR"),
    ("Rs. 40", "money", 40, "INR"),
    ("50,000 rupees", "money", 50000, "INR"),
    ("2 weeks", "duration", 14, "days"),
    ("fifteen days", "duration", 15, "days"),
    ("3 working days", "duration", 3, "business_days"),
    ("48 hours", "duration", 48, "hours"),
    ("1 year", "duration", 12, "months"),
    ("1.5%", "percent", 1.5, "%"),
    ("2 per cent", "percent", 2, "%"),
])
def test_values_are_normalised(text, kind, amount, unit):
    value = parse_value(text, kind)
    assert value.amount == pytest.approx(amount) and value.unit == unit


def test_dates_in_any_common_format_are_the_same_day():
    days = {parse_value(t, "date").amount for t in
            ["2 November 2026", "November 2, 2026", "2026-11-02", "02/11/2026", "2nd Nov 2026"]}
    assert len(days) == 1


def test_working_days_never_equal_calendar_days():
    assert not parse_value("3 working days", "duration").same_as(parse_value("3 days", "duration"))


def test_a_locked_value_must_be_unambiguous():
    assert len(extract_values("Rs 40 or Rs 50", "money")) == 2
    with pytest.raises(ValueError):
        parse_value("Rs 40 or Rs 50", "money")
    with pytest.raises(ValueError):
        parse_value("soon", "duration")


# ------------------------------------------------------------------ verdicts
def test_question_scope_catches_a_bare_wrong_number(lock):
    result = lock.check("How many days do I have to return my order?", "You have 30 days.")
    check = by_key(result)["refund_window"]
    assert check.verdict == "mismatch" and check.action == "block" and check.scope == "question"
    assert result.floor == Decision.ESCALATE


def test_the_correct_value_passes(lock):
    result = lock.check("What is the refund window?", "The refund window is 15 days.")
    assert by_key(result)["refund_window"].verdict == "confirmed"
    assert result.floor is None and not result.reasons


def test_same_value_written_differently_still_passes(lock):
    result = lock.check("", "You can request a refund within two weeks and one day? No: the "
                            "refund window is fifteen days.")
    assert by_key(result)["refund_window"].verdict == "confirmed"


def test_level_two_corrects_the_answer(lock):
    answer = "Employees get 18 days of casual leave per year."
    result = lock.check("", answer)
    assert result.floor == Decision.CAVEAT
    assert result.corrected_answer == "Employees get 12 days of casual leave per year."
    assert any("12 days" in note for note in result.notes)


def test_clauses_keep_neighbouring_facts_apart(lock):
    right = ("The hotel limit is Rs 7,500 per night in metro cities and Rs 4,000 per night "
             "in other cities.")
    checks = by_key(lock.check("", right))
    assert checks["hotel_limit_metro"].verdict == "confirmed"
    assert checks["hotel_limit_other"].verdict == "confirmed"

    swapped = right.replace("7,500", "X").replace("4,000", "7,500").replace("X", "4,000")
    result = lock.check("", swapped)
    checks = by_key(result)
    assert checks["hotel_limit_metro"].action == "block"
    assert checks["hotel_limit_other"].action == "note"
    assert result.floor == Decision.ESCALATE


def test_a_negated_alias_does_not_claim_the_other_fact():
    store = facts_store()
    store.update("hotel_limit_other", aliases=["hotel limit non-metro"])
    store.update("hotel_limit_metro", aliases=["hotel limit mumbai"])
    answer = ("The hotel limit is Rs 7,500 per night in metro cities and Rs 4,000 per night "
              "in other cities.")
    checks = by_key(FactLock(store).check("", answer))
    assert checks["hotel_limit_metro"].verdict == "confirmed"
    assert checks["hotel_limit_other"].verdict == "confirmed"


def test_unrelated_answers_are_left_alone(lock):
    result = lock.check("What are office hours?", "Office hours are 9:30 AM to 6:30 PM.")
    assert result.checks == [] and result.floor is None


def test_a_superseded_value_is_reported_as_outdated():
    store = facts_store()
    store.update("casual_leave", value="10 days", version="2027")
    result = FactLock(store).check("", "You get 12 days of casual leave.")
    check = by_key(result)["casual_leave"]
    assert check.verdict == "outdated" and check.outdated_version == "2026"


def test_regulated_facts_must_cite_the_current_version(lock):
    answer = "We answer requests to delete personal data within 30 days."
    wrong_source = [EvidenceItem(text="...", source="Blog.pdf", version="1")]
    right_source = [EvidenceItem(text="...", source=PRIVACY, version="2.0")]
    assert by_key(lock.check("", answer, wrong_source))["data_request_days"].verdict == "uncited"
    assert lock.check("", answer, wrong_source).requires_approval
    assert by_key(lock.check("", answer, right_source))["data_request_days"].verdict == "confirmed"


def test_rupee_abbreviation_does_not_split_the_sentence(lock):
    checks = by_key(lock.check("", "The hotel limit in metro cities is Rs. 7,500 per night."))
    assert checks["hotel_limit_metro"].verdict == "confirmed"


# ------------------------------------------------------------ evaluator path
def evaluator_with(store):
    return Evaluator([FixedSignal(n, v) for n, v in GOOD.items()], fact_lock=FactLock(store))


@pytest.mark.parametrize("evidence", [
    [{"text": "Refunds are accepted within 30 days.", "source": "Old_Refund_Policy.pdf"}],
    [{"text": "Refunds are accepted within 15 days.", "source": "Refund_Policy.pdf"}],
    [{"text": "Our office is in Pune.", "source": "About.pdf"}],
])
def test_decision_does_not_move_with_retrieval(evidence):
    """Stale, correct or irrelevant chunks: the locked fact gives the same verdict."""
    request = EvaluateRequest(query="How many days do I have to return my order?",
                              answer="You have 30 days.", evidence=evidence)
    response = evaluator_with(facts_store()).evaluate(request)
    assert response.decision == Decision.ESCALATE
    assert ReasonCode.LOCKED_FACT_MISMATCH in {r.code for r in response.reasons}
    assert response.explanation.decisive_rule == "veto:locked_fact"
    assert response.trace["decision"] == "ESCALATE"


def test_evaluator_without_facts_is_unchanged():
    request = EvaluateRequest(query="Refund window?", answer="30 days.",
                              evidence=[{"text": "Refunds within 30 days."}])
    plain = Evaluator([FixedSignal(n, v) for n, v in GOOD.items()]).evaluate(request)
    empty = evaluator_with(FactStore(":memory:")).evaluate(request)
    assert plain.decision == empty.decision == Decision.ANSWER
    assert empty.fact_checks == []


def test_level_two_caveat_carries_the_corrected_answer():
    request = EvaluateRequest(query="Casual leave?", answer="Employees get 18 days of casual leave.",
                              evidence=[{"text": "Employees get 18 days of casual leave."}])
    response = evaluator_with(facts_store()).evaluate(request)
    assert response.decision == Decision.CAVEAT
    assert response.corrected_answer == "Employees get 12 days of casual leave."
    assert "12 days" in response.caveat_text


# --------------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path):
    evaluator = Evaluator([FixedSignal(n, v) for n, v in GOOD.items()])
    app = create_app(evaluator, audit_logger=AuditLogger(str(tmp_path / "a.db")),
                     escalation_queue=EscalationQueue(str(tmp_path / "e.db")),
                     fact_store=FactStore(str(tmp_path / "f.db")), auth_enabled=False)
    return TestClient(app)


LEAVE = {"key": "casual_leave", "label": "casual leave", "kind": "duration", "value": "18 days",
         "level": 3, "source": "HR_Leave_Policy.pdf", "version": "2024"}


def test_api_lock_evaluate_update_and_impact(client):
    assert client.post("/v1/facts", json=LEAVE).status_code == 201
    assert client.post("/v1/facts", json=LEAVE).status_code == 409

    ev = {"query": "How much casual leave?", "answer": "You get 18 days of casual leave.",
          "evidence": [{"text": "18 days of casual leave."}]}
    first = client.post("/v1/evaluate", json=ev).json()
    assert first["decision"] == "ANSWER"
    assert first["fact_checks"][0]["verdict"] == "confirmed"

    changed = client.put("/v1/facts/casual_leave", json={"value": "12 days", "version": "2026"})
    assert changed.status_code == 200
    impact = changed.json()["impact"]
    assert impact["counts"]["outdated"] == 1 and impact["delivered_wrong"] == 1
    assert impact["affected"][0]["request_id"] == first["request_id"]
    assert impact["affected"][0]["old_version"] == "2024"

    second = client.post("/v1/evaluate", json=ev).json()
    assert second["decision"] == "ESCALATE"
    assert second["fact_checks"][0]["verdict"] == "outdated"
    escalations = client.get("/v1/escalations").json()
    assert any(e["request_id"] == second["request_id"] for e in escalations)

    history = client.get("/v1/facts/casual_leave/history").json()["versions"]
    assert [v["value"] for v in history] == ["12 days", "18 days"]
    assert [v["status"] for v in history] == ["active", "superseded"]


def test_api_rejects_values_that_do_not_parse(client):
    bad = {**LEAVE, "value": "a fortnight"}
    assert client.post("/v1/facts", json=bad).status_code == 422
    assert client.post("/v1/facts", json={**LEAVE, "kind": "colour"}).status_code == 422
    assert client.post("/v1/facts", json={**LEAVE, "level": 5}).status_code == 422


def test_api_check_and_suggest(client):
    client.post("/v1/facts", json=LEAVE)
    r = client.post("/v1/facts/check", json={"answer": "Casual leave is 20 days a year."}).json()
    assert r["decision_floor"] == "ESCALATE" and r["checks"][0]["stated"] == "20 days"

    text = "The hotel limit is Rs 6,000 per night. Claims must be filed within 30 days."
    candidates = client.post("/v1/facts/suggest", json={"text": text}).json()["candidates"]
    assert {c["value"] for c in candidates} == {"Rs 6,000", "30 days"}


def test_api_retire(client):
    client.post("/v1/facts", json=LEAVE)
    assert client.delete("/v1/facts/casual_leave").status_code == 200
    assert client.get("/v1/facts").json()["facts"] == []
    assert client.delete("/v1/facts/casual_leave").status_code == 404


# -------------------------------------------------------------------- auth
def test_roles_for_fact_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("AEGIS_ADMIN_PASSWORD", "Adm1n-Passw0rd!")
    monkeypatch.setenv("AEGIS_API_KEYS", "svc-key")
    users = UserStore(str(tmp_path / "u.db"))
    app = create_app(Evaluator([FixedSignal(n, v) for n, v in GOOD.items()]),
                     audit_logger=AuditLogger(str(tmp_path / "a.db")),
                     escalation_queue=EscalationQueue(str(tmp_path / "e.db")),
                     fact_store=FactStore(str(tmp_path / "f.db")), user_store=users,
                     auth_enabled=True)
    users.create_user("viewer@example.com", "V1ewer-Passw0rd!", "viewer")

    anon = TestClient(app)
    assert anon.get("/v1/facts").status_code == 401

    viewer = TestClient(app)
    viewer.post("/v1/auth/login", json={"email": "viewer@example.com", "password": "V1ewer-Passw0rd!"})
    assert viewer.get("/v1/facts").status_code == 200
    assert viewer.post("/v1/facts", json=LEAVE).status_code == 403

    service = TestClient(app, headers={"X-API-Key": "svc-key"})
    assert service.post("/v1/facts/check", json={"answer": "x 1 day"}).status_code == 200
    assert service.post("/v1/facts", json=LEAVE).status_code == 403

    admin = TestClient(app)
    admin.post("/v1/auth/login", json={"email": "admin@example.com", "password": "Adm1n-Passw0rd!"})
    assert admin.post("/v1/facts", json=LEAVE).status_code == 201
    # A cookie-authenticated write from a foreign site is refused (CSRF check).
    assert admin.put("/v1/facts/casual_leave", json={"value": "1 day"},
                     headers={"Origin": "https://evil.example"}).status_code == 403
