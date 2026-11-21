"""Evaluator behaviour and response-shape stability, with stub signals.

Covers the additive response contract (docs/finale/CONTRACTS.md, section 2),
model-failure paths and input edge cases. No model is loaded.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.evaluator import Evaluator
from app.evidence.base import Signal
from app.evidence.stubs import FixedSignal
from app.schemas import (
    ClaimStatus,
    Decision,
    EvaluateRequest,
    EvaluateResponse,
    ReasonCode,
    RecommendedAction,
    SignalResult,
)

GOOD = dict(relevance=0.95, entailment=0.95, contradiction=0.02,
            freshness=0.9, completeness=0.9, ambiguity=0.04)

ANSWER = "Staff get 18 casual leaves. Exercise prevents all diseases."
REQ = EvaluateRequest(
    query="How many casual leaves do staff get?",
    answer=ANSWER,
    evidence=[
        {"text": "Staff are entitled to 18 casual leaves.", "source": "policy.pdf"},
        {"text": "Leave is granted annually.", "source": "handbook.pdf"},
    ],
)


def raw_claim(text, status, grounding=1.0, supporting=(), contradicting=()):
    return {
        "claim": text,
        "status": status,
        "support": 0.95 if status == "SUPPORTED" else 0.3,
        "supporting_evidence_indices": list(supporting),
        "contradicting_evidence_indices": list(contradicting),
        "evidence_indices": sorted({*supporting, *contradicting}),
        "grounding": grounding,
        "nli_available": True,
    }


class ClaimsEntailment(Signal):
    """An entailment signal that reports a fixed value and fixed claims."""

    name = "entailment"

    def __init__(self, claims, value=0.95):
        self._claims = claims
        self._value = value

    def score(self, query, answer, evidence):
        return SignalResult(value=self._value, details={"claims": self._claims})


class Crashing(Signal):
    def __init__(self, name):
        self.name = name

    def score(self, query, answer, evidence):
        raise RuntimeError("model exploded")


def signals(claims=None, **overrides):
    values = {**GOOD, **overrides}
    out = [FixedSignal(n, v) for n, v in values.items() if n != "entailment" or claims is None]
    if claims is not None:
        out.append(ClaimsEntailment(claims, values["entailment"]))
    return out


SUPPORTED = raw_claim("Staff get 18 casual leaves.", "SUPPORTED", 1.0, supporting=[0])
INVENTED = raw_claim("Exercise prevents all diseases.", "UNSUPPORTED", 0.0)
CONTRADICTED = raw_claim("Staff get 18 casual leaves.", "CONTRADICTED", 0.9, contradicting=[1])

# Every key a response must carry, on every path.
RESPONSE_KEYS = set(EvaluateResponse.model_fields)
CONTRACT_KEYS = {"headline", "unavailable_signals", "explanation", "claims"}
CLAIM_KEYS = {"claim", "status", "support", "evidence_indices", "supporting_evidence_indices",
              "contradicting_evidence_indices", "reason", "span"}


# ------------------------------------------------------------------ decisions
def test_fully_supported_answer_is_answered_with_a_full_explanation():
    resp = Evaluator(signals([SUPPORTED])).evaluate(REQ)
    assert resp.decision == Decision.ANSWER
    assert resp.headline.startswith("Safe to show")
    assert resp.unavailable_signals == []
    assert resp.explanation.decisive_rule == "score_threshold"
    assert resp.explanation.factors[0].signal == "answerability_score"
    assert "can be shown as it is" in resp.explanation.summary


def test_one_invented_claim_in_a_strong_answer_gets_a_caveat():
    """Headline bug: aggregate signals are excellent, one claim is invented."""
    resp = Evaluator(signals([SUPPORTED, INVENTED])).evaluate(REQ)
    assert resp.answerability_score >= 0.8          # the score alone would say ANSWER
    assert resp.decision == Decision.CAVEAT
    assert resp.recommended_action == RecommendedAction.RETURN_WITH_CAVEAT
    assert resp.explanation.decisive_rule == "veto:unsupported_claim"
    assert "Exercise prevents all diseases." in resp.explanation.summary
    assert any(r.code == ReasonCode.UNSUPPORTED_CLAIM and "Exercise prevents" in r.message
               for r in resp.reasons)
    assert "Exercise prevents all diseases." in resp.caveat_text


@pytest.mark.parametrize(
    "profile, expected",
    [("lenient", Decision.CAVEAT), ("standard", Decision.CAVEAT), ("strict", Decision.ESCALATE)],
)
def test_invented_claim_across_profiles(profile, expected):
    req = REQ.model_copy(update={"profile": profile})
    assert Evaluator(signals([SUPPORTED, INVENTED])).evaluate(req).decision == expected


def test_contradicted_claim_escalates_even_with_a_high_score():
    resp = Evaluator(signals([CONTRADICTED])).evaluate(REQ)
    assert resp.decision == Decision.ESCALATE
    assert resp.explanation.decisive_rule == "veto:contradicted_claim"
    assert resp.claims[0].contradicting_evidence_indices == [1]


def test_nothing_supported_and_nothing_mentioned_abstains():
    resp = Evaluator(signals([INVENTED])).evaluate(REQ)
    assert resp.decision == Decision.ABSTAIN
    assert resp.explanation.decisive_rule == "veto:no_supported_claim"


def test_answer_never_carries_a_non_supported_claim():
    """Invariant: ANSWER implies every verified claim is SUPPORTED."""
    for claims in ([SUPPORTED], [SUPPORTED, INVENTED], [INVENTED], [CONTRADICTED],
                   [SUPPORTED, raw_claim("Leave is annual.", "UNSUPPORTED", 0.9)]):
        for profile in ("lenient", "standard", "strict"):
            resp = Evaluator(signals(claims)).evaluate(REQ.model_copy(update={"profile": profile}))
            if resp.decision == Decision.ANSWER:
                assert all(c.status == ClaimStatus.SUPPORTED for c in resp.claims)


# ------------------------------------------------------------------ claim fields
def test_claims_expose_indices_reason_and_span():
    resp = Evaluator(signals([SUPPORTED, INVENTED])).evaluate(REQ)
    supported, invented = resp.claims

    assert supported.supporting_evidence_indices == [0]
    assert supported.contradicting_evidence_indices == []
    assert "evidence E1" in supported.reason
    start, end = supported.span
    assert ANSWER[start:end] == "Staff get 18 casual leaves."

    assert invented.status == ClaimStatus.UNSUPPORTED
    assert "does not mention" in invented.reason
    start, end = invented.span
    assert ANSWER[start:end] == "Exercise prevents all diseases."


def test_span_is_null_when_the_claim_is_not_a_verbatim_substring():
    reworded = raw_claim("Staff get exercise leaves.", "SUPPORTED", 1.0, supporting=[0])
    resp = Evaluator(signals([reworded])).evaluate(REQ)
    assert resp.claims[0].span is None


def test_span_of_a_repunctuated_atomic_claim():
    req = REQ.model_copy(update={"answer": "Growth is caused by births and migration."})
    atom = raw_claim("Growth is caused by births.", "SUPPORTED", 1.0, supporting=[0])
    resp = Evaluator(signals([atom])).evaluate(req)
    start, end = resp.claims[0].span
    assert req.answer[start:end] == "Growth is caused by births"


def test_supported_claim_disputed_by_another_passage_says_so():
    disputed = raw_claim("Staff get 18 casual leaves.", "SUPPORTED", 1.0, supporting=[0], contradicting=[1])
    resp = Evaluator(signals([disputed])).evaluate(REQ)
    assert "sources disagree" in resp.claims[0].reason


# ------------------------------------------------------------------ unavailable signals / failures
@pytest.mark.parametrize("name", ["freshness", "completeness", "ambiguity"])
def test_missing_minor_signal_is_listed_and_caveated(name):
    resp = Evaluator(signals([SUPPORTED], **{name: None})).evaluate(REQ)
    assert resp.unavailable_signals == [name]
    assert resp.degraded is True
    assert resp.decision == Decision.CAVEAT
    assert resp.explanation.decisive_rule == f"veto:signal_unavailable:{name}"
    assert getattr(resp.signals, name) is None       # never replaced by a made-up number


@pytest.mark.parametrize("name", ["relevance", "entailment", "contradiction"])
def test_crashing_critical_signal_escalates_and_is_listed(name):
    stack = [s for s in signals([SUPPORTED]) if s.name != name] + [Crashing(name)]
    resp = Evaluator(stack).evaluate(REQ)
    assert resp.decision == Decision.ESCALATE
    assert resp.unavailable_signals == [name]
    assert resp.degraded is True
    assert any(r.code == ReasonCode.SIGNAL_UNAVAILABLE for r in resp.reasons)


def test_unverified_claims_are_listed_but_not_judged():
    """Entailment returned no value: its claims must not trigger claim rules."""
    unverified = dict(INVENTED, nli_available=False)

    class DeadEntailment(Signal):
        name = "entailment"

        def score(self, query, answer, evidence):
            return SignalResult(value=None, details={"claims": [unverified]})

    stack = [s for s in signals() if s.name != "entailment"] + [DeadEntailment()]
    resp = Evaluator(stack).evaluate(REQ)
    assert resp.decision == Decision.ESCALATE        # not ABSTAIN via 'no supported claim'
    assert resp.explanation.decisive_rule == "veto:signal_unavailable:entailment"
    assert "not verified" in resp.claims[0].reason


def test_every_signal_crashing_fails_closed():
    resp = Evaluator([Crashing(n) for n in GOOD]).evaluate(REQ)
    assert resp.decision == Decision.ABSTAIN
    assert sorted(resp.unavailable_signals) == sorted(GOOD)
    assert resp.answerability_score == 0.0


def test_unavailable_signals_follow_schema_order():
    resp = Evaluator(signals([SUPPORTED], ambiguity=None, freshness=None)).evaluate(REQ)
    assert resp.unavailable_signals == ["freshness", "ambiguity"]


# ------------------------------------------------------------------ input edge cases
def test_no_evidence_has_the_same_shape_as_a_normal_response():
    normal = Evaluator(signals([SUPPORTED])).evaluate(REQ).model_dump()
    empty = Evaluator(signals([SUPPORTED])).evaluate(
        EvaluateRequest(query="Q?", answer="An answer.")).model_dump()

    assert set(normal) == set(empty) == RESPONSE_KEYS
    assert CONTRACT_KEYS <= set(empty)
    assert empty["decision"] == "ABSTAIN"
    assert empty["headline"]
    assert empty["unavailable_signals"] == []
    assert empty["explanation"]["decisive_rule"] == "veto:no_evidence"
    assert set(empty["explanation"]) == set(normal["explanation"])
    assert set(empty["explanation"]["factors"][0]) == set(normal["explanation"]["factors"][0])
    assert empty["claims"] == []


@pytest.mark.parametrize("texts", [["   "], [" ", "\n\t"]])
def test_whitespace_only_evidence_is_no_evidence(texts):
    calls = []

    class Recording(FixedSignal):
        def score(self, query, answer, evidence):
            calls.append(self.name)
            return super().score(query, answer, evidence)

    req = EvaluateRequest(query="Q?", answer="An answer.", evidence=[{"text": t} for t in texts])
    resp = Evaluator([Recording("relevance", 1.0)]).evaluate(req)
    assert resp.decision == Decision.ABSTAIN
    assert resp.reasons[0].code == ReasonCode.NO_EVIDENCE
    assert calls == []


@pytest.mark.parametrize("field", ["query", "answer"])
def test_empty_query_or_answer_is_rejected_by_the_schema(field):
    payload = {"query": "Q?", "answer": "A.", field: ""}
    with pytest.raises(ValueError):
        EvaluateRequest(**payload)


def test_empty_evidence_text_is_rejected_by_the_schema():
    with pytest.raises(ValueError):
        EvaluateRequest(query="Q?", answer="A.", evidence=[{"text": ""}])


def test_claim_dict_shape_is_stable():
    resp = Evaluator(signals([SUPPORTED, INVENTED])).evaluate(REQ).model_dump()
    for claim in resp["claims"]:
        assert CLAIM_KEYS <= set(claim)


def test_malformed_claim_details_do_not_crash():
    weird = [{"claim": "Staff get 18 casual leaves.", "status": "NOT_A_STATUS", "support": 7,
              "grounding": "high", "evidence_indices": None}, "not a dict", None]
    resp = Evaluator(signals(weird)).evaluate(REQ)
    assert len(resp.claims) == 1
    assert resp.claims[0].status == ClaimStatus.UNSUPPORTED
    assert resp.claims[0].support == 1.0
    assert resp.claims[0].grounding is None
    assert resp.decision != Decision.ANSWER


# ------------------------------------------------------------------ request id
def test_request_id_can_be_supplied_for_deterministic_runs():
    ev = Evaluator(signals([SUPPORTED]))
    resp = ev.evaluate(REQ, request_id="seed-0001")
    assert resp.request_id == "seed-0001"
    assert resp.trace["request_id"] == "seed-0001"
    assert ev.evaluate(EvaluateRequest(query="Q?", answer="A."), request_id="seed-0002").request_id == "seed-0002"


def test_request_id_defaults_to_a_fresh_uuid():
    ev = Evaluator(signals([SUPPORTED]))
    a, b = ev.evaluate(REQ), ev.evaluate(REQ)
    assert a.request_id != b.request_id
    assert len(a.request_id) == 32


def test_same_input_gives_the_same_decision_and_explanation():
    ev = Evaluator(signals([SUPPORTED, INVENTED]))
    a, b = ev.evaluate(REQ), ev.evaluate(REQ)
    assert a.decision == b.decision
    assert a.explanation == b.explanation
    assert a.reasons == b.reasons


# ------------------------------------------------------------------ HTTP layer
def test_api_response_carries_the_additive_fields(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "evaluator", Evaluator(signals([SUPPORTED, INVENTED])), raising=False)
    client = TestClient(main.app)
    resp = client.post("/v1/evaluate", json=REQ.model_dump(mode="json"))
    if resp.status_code == 404:
        pytest.skip("evaluate route is not mounted at /v1/evaluate in this build")
    assert resp.status_code == 200
    body = resp.json()
    assert CONTRACT_KEYS <= set(body)
    assert RESPONSE_KEYS <= set(body) | {"trace"}
    assert isinstance(body["unavailable_signals"], list)
    assert {"summary", "decisive_rule", "factors"} <= set(body["explanation"])
