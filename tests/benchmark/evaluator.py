"""Benchmark evaluation harness for the AEGIS Middleware.

Evaluates benchmark cases through the Evaluator and calculates:
  * Decision Accuracy
  * Coverage (fraction of answers allowed through: ANSWER / CAVEAT)
  * Selective Accuracy (accuracy among allowed answers)
  * Abstention Precision (precision when refusing/escalating)
  * Latency statistics
  * Detailed per-case breakdown

Per the Aegis execution plan (§9.3), development and tuning are conducted
strictly on DEV_CASES. The locked test set (TEST_CASES) is preserved to prevent
overfitting and data leakage.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any, Dict, List, Optional

from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.schemas import Decision, EvaluateResponse
from tests.benchmark.test_cases import BENCHMARK_CASES, DEV_CASES, TEST_CASES


def evaluate_case(evaluator: Evaluator, case: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    response: EvaluateResponse = evaluator.evaluate(case["request"])
    latency_ms = (time.perf_counter() - t0) * 1000

    actual_decision = response.decision.value
    expected_decision = case["expected_decision"]
    matched = actual_decision == expected_decision

    return {
        "name": case["name"],
        "split": case.get("split", "dev"),
        "expected_decision": expected_decision,
        "actual_decision": actual_decision,
        "matched": matched,
        "answerability_score": response.answerability_score,
        "recommended_action": response.recommended_action.value,
        "signals": {k: v for k, v in response.signals.model_dump().items() if v is not None},
        "reasons": [r.message for r in response.reasons],
        "clarifying_question": response.clarifying_question,
        "caveat_text": response.caveat_text,
        "latency_ms": round(latency_ms, 2),
    }


def run_benchmark(
    cases: Optional[List[dict[str, Any]]] = None,
    evaluator: Optional[Evaluator] = None,
    allow_locked_test_set: bool = False,
) -> dict[str, Any]:
    """Execute benchmark cases through the Evaluator and compute evaluation metrics.

    Args:
        cases: The cases to evaluate (defaults to DEV_CASES).
        evaluator: The Evaluator instance to use (defaults to Evaluator(default_signals())).
        allow_locked_test_set: Set to True to intentionally run on TEST_CASES.
    """
    if cases is None:
        cases = DEV_CASES

    has_test_cases = any(c.get("split") == "test" for c in cases)
    if has_test_cases and not allow_locked_test_set:
        print(
            "NOTE: Test-set cases detected. Per Aegis Plan §9.3, tuning and iterative "
            "evaluation should use DEV_CASES. Ensure semantics are frozen before interpreting test results."
        )

    if evaluator is None:
        evaluator = Evaluator(default_signals())

    results = []
    latencies = []

    for case in cases:
        case_res = evaluate_case(evaluator, case)
        results.append(case_res)
        latencies.append(case_res["latency_ms"])

    total = len(results)
    matches = sum(1 for r in results if r["matched"])
    accuracy = (matches / total) if total > 0 else 0.0

    # Coverage: Allowed answers (ANSWER or CAVEAT) vs Refusals (ESCALATE or ABSTAIN)
    allowed = sum(1 for r in results if r["actual_decision"] in {"ANSWER", "CAVEAT"})
    coverage = (allowed / total) if total > 0 else 0.0

    # Selective Accuracy: Accuracy among answers allowed through
    allowed_and_correct = sum(
        1 for r in results if r["actual_decision"] in {"ANSWER", "CAVEAT"} and r["matched"]
    )
    selective_accuracy = (allowed_and_correct / allowed) if allowed > 0 else 0.0

    # Abstention / Escalation Precision: When we refused/escalated, were we expected to?
    refused = sum(1 for r in results if r["actual_decision"] in {"ABSTAIN", "ESCALATE"})
    refused_and_correct = sum(
        1 for r in results if r["actual_decision"] in {"ABSTAIN", "ESCALATE"} and r["matched"]
    )
    abstention_precision = (refused_and_correct / refused) if refused > 0 else 0.0

    metrics = {
        "total_cases": total,
        "matched_cases": matches,
        "accuracy": round(accuracy, 4),
        "coverage": round(coverage, 4),
        "selective_accuracy": round(selective_accuracy, 4),
        "abstention_precision": round(abstention_precision, 4),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2) if latencies else 0.0,
            "median": round(statistics.median(latencies), 2) if latencies else 0.0,
            "min": round(min(latencies), 2) if latencies else 0.0,
            "max": round(max(latencies), 2) if latencies else 0.0,
        },
        "results": results,
    }

    return metrics


def print_report(metrics: dict[str, Any]) -> None:
    print("=" * 78)
    print("AEGIS BENCHMARK EVALUATION REPORT")
    print("=" * 78)
    print(f"Total Cases Evaluated: {metrics['total_cases']}")
    print(f"Matches:              {metrics['matched_cases']}/{metrics['total_cases']} ({metrics['accuracy'] * 100:.1f}%)")
    print(f"Coverage:             {metrics['coverage'] * 100:.1f}%")
    print(f"Selective Accuracy:   {metrics['selective_accuracy'] * 100:.1f}%")
    print(f"Abstention Precision: {metrics['abstention_precision'] * 100:.1f}%")
    print(f"Median Latency:       {metrics['latency_ms']['median']} ms")
    print("-" * 78)
    print(f"{'Case Name':<32} {'Split':<5} {'Expected':<9} {'Actual':<9} {'Match':<6} {'Score':<6}")
    print("-" * 78)
    for r in metrics["results"]:
        match_str = "YES" if r["matched"] else "NO"
        print(f"{r['name']:<32} {r['split']:<5} {r['expected_decision']:<9} {r['actual_decision']:<9} {match_str:<6} {r['answerability_score']:<6.2f}")
    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AEGIS benchmark through evaluator.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all 15 benchmark cases (includes locked test set).",
    )
    parser.add_argument(
        "--test-set",
        action="store_true",
        help="Run only the locked test set.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON metrics.",
    )
    args = parser.parse_args()

    if args.all:
        cases = BENCHMARK_CASES
        allow_locked = True
    elif args.test_set:
        cases = TEST_CASES
        allow_locked = True
    else:
        cases = DEV_CASES
        allow_locked = False

    metrics = run_benchmark(cases=cases, allow_locked_test_set=allow_locked)

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print_report(metrics)


if __name__ == "__main__":
    main()
