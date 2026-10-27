from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.schemas import Decision, EvaluateResponse, RecommendedAction
from tests.benchmark.evaluator import evaluate_case, run_benchmark
from tests.benchmark.test_cases import BENCHMARK_CASES, DEV_CASES, TEST_CASES


def test_benchmark_has_expected_coverage():
    assert len(BENCHMARK_CASES) == 20
    assert len(DEV_CASES) == 12
    assert len(TEST_CASES) == 8

    all_decisions = {case["expected_decision"] for case in BENCHMARK_CASES}
    assert all_decisions == {"ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"}

    dev_decisions = {case["expected_decision"] for case in DEV_CASES}
    assert dev_decisions == {"ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"}


def test_benchmark_cases_have_required_fields():
    valid_failure_types = {
        "NONE",
        "NO_EVIDENCE",
        "LOW_RELEVANCE",
        "UNSUPPORTED_CLAIM",
        "CONTRADICTION",
        "STALE_EVIDENCE",
        "INCOMPLETE_EVIDENCE",
        "AMBIGUOUS_QUERY",
        "SIGNAL_UNAVAILABLE",
    }

    for case in BENCHMARK_CASES:
        assert case["name"]
        assert case["request"].query
        assert case["request"].answer
        assert case["expected_decision"]
        assert case["expected_reason"]
        assert case["split"] in {"dev", "test"}
        assert case.get("failure_type") in valid_failure_types

        assert case["expected_decision"] in {
            "ANSWER",
            "CAVEAT",
            "ESCALATE",
            "ABSTAIN",
        }


def test_benchmark_case_names_are_unique():
    names = [case["name"] for case in BENCHMARK_CASES]
    assert len(names) == len(set(names))


def test_dev_cases_execute_through_evaluator():
    """Verify that development benchmark cases execute cleanly through the evaluator.

    Ensures the live evaluator with real ambiguity signal computes valid
    decisions, bounded answerability scores, and appropriate reasons.
    """
    evaluator = Evaluator(default_signals())

    for case in DEV_CASES:
        response = evaluator.evaluate(case["request"])
        assert isinstance(response, EvaluateResponse)
        assert isinstance(response.decision, Decision)
        assert 0.0 <= response.answerability_score <= 1.0
        assert response.latency_ms >= 0.0

        # When query is ambiguous, verify real AmbiguitySignal drives escalation
        if case["name"] == "ambiguous_query_escalate":
            assert response.signals.ambiguity is not None
            assert response.signals.ambiguity >= 0.30
            assert response.decision == Decision.ESCALATE
            assert response.recommended_action == RecommendedAction.ASK_CLARIFYING_QUESTION


def test_benchmark_runner_produces_metrics():
    """Verify the benchmark execution harness computes coverage and accuracy metrics on DEV_CASES."""
    evaluator = Evaluator(default_signals())
    metrics = run_benchmark(cases=DEV_CASES, evaluator=evaluator)

    assert metrics["total_cases"] == len(DEV_CASES)
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert 0.0 <= metrics["coverage"] <= 1.0
    assert len(metrics["results"]) == len(DEV_CASES)


def test_locked_test_set_isolation():
    """Confirm the test set is properly partitioned and marked as locked.

    Per Aegis Plan §9.3:
    The test set is locked and preserved for the final evaluation run once all
    team semantics are settled, avoiding premature tuning leakage.
    """
    assert len(TEST_CASES) == 8
    for case in TEST_CASES:
        assert case["split"] == "test"
