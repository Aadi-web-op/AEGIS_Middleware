"""Explanation Check: scores whether decision headlines and reasons match labelled failure types.

Per "Aegis Decision Graph (Neo4j Add-on): Team Brief" (Oct 22, 2026), Section 10:
"Explanation check: take 20 benchmark cases and score whether each headline and
reason matches the labelled failure type. Report the result honestly."

Usage:
    python -m scripts.explanation_check [--json]
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any, Dict, List, Optional

from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.graph.templates import HEADLINES, REASON_TEMPLATES, render_headline, render_reason
from app.schemas import ReasonCode
from tests.benchmark.test_cases import BENCHMARK_CASES

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("explanation_check")


def run_explanation_check(
    cases: Optional[List[Dict[str, Any]]] = None,
    evaluator: Optional[Evaluator] = None,
) -> Dict[str, Any]:
    """Score explanation faithfulness across benchmark cases against their labelled failure types."""
    if cases is None:
        cases = BENCHMARK_CASES

    if evaluator is None:
        evaluator = Evaluator(default_signals())

    case_results: List[Dict[str, Any]] = []
    headline_matches = 0
    reason_matches = 0
    full_matches = 0

    for case in cases:
        name = case["name"]
        expected_decision = case["expected_decision"]
        failure_type = case.get("failure_type", "NONE")
        expected_headline = HEADLINES.get(expected_decision, "")

        # Run evaluation
        response = evaluator.evaluate(case["request"])
        actual_decision = response.decision.value
        actual_headline = render_headline(actual_decision)

        # Check headline match against expected decision
        headline_match = actual_headline == expected_headline

        # Check reason / failure-type match
        actual_codes = {r.code.value for r in response.reasons}

        if failure_type == "NONE":
            # For answerable cases, success means no failure reasons
            reason_match = len(actual_codes) == 0 or actual_decision == "ANSWER"
            expected_reason_text = "No failure reason (answer supported)."
        else:
            reason_match = failure_type in actual_codes
            expected_reason_text = REASON_TEMPLATES.get(failure_type, f"Reason for {failure_type}")

        if headline_match:
            headline_matches += 1
        if reason_match:
            reason_matches += 1
        if headline_match and reason_match:
            full_matches += 1

        case_results.append({
            "name": name,
            "split": case.get("split", "dev"),
            "expected_decision": expected_decision,
            "actual_decision": actual_decision,
            "failure_type": failure_type,
            "headline_match": headline_match,
            "reason_match": reason_match,
            "full_match": headline_match and reason_match,
            "actual_headline": actual_headline,
            "expected_headline": expected_headline,
            "actual_codes": sorted(list(actual_codes)),
            "reasons": [r.message for r in response.reasons],
        })

    total = len(cases)
    report = {
        "total_cases": total,
        "headline_matches": headline_matches,
        "headline_accuracy": round((headline_matches / total) * 100, 1) if total > 0 else 0.0,
        "reason_matches": reason_matches,
        "reason_accuracy": round((reason_matches / total) * 100, 1) if total > 0 else 0.0,
        "full_matches": full_matches,
        "full_accuracy": round((full_matches / total) * 100, 1) if total > 0 else 0.0,
        "cases": case_results,
    }
    return report


def print_report(report: Dict[str, Any]) -> None:
    print("=" * 86)
    print("AEGIS 20-CASE EXPLANATION CHECK REPORT")
    print("=" * 86)
    print(f"Total Cases:         {report['total_cases']}")
    print(f"Headline Accuracy:   {report['headline_matches']}/{report['total_cases']} ({report['headline_accuracy']}%)")
    print(f"Reason Accuracy:     {report['reason_matches']}/{report['total_cases']} ({report['reason_accuracy']}%)")
    print(f"Complete Matches:    {report['full_matches']}/{report['total_cases']} ({report['full_accuracy']}%)")
    print("-" * 86)
    print(f"{'Case Name':<32} {'Exp Dec':<8} {'Act Dec':<8} {'Failure Type':<18} {'Head':<5} {'Reason':<6}")
    print("-" * 86)
    for c in report["cases"]:
        h_mark = "PASS" if c["headline_match"] else "FAIL"
        r_mark = "PASS" if c["reason_match"] else "FAIL"
        print(f"{c['name']:<32} {c['expected_decision']:<8} {c['actual_decision']:<8} {c['failure_type']:<18} {h_mark:<5} {r_mark:<6}")
    print("=" * 86)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 20-case explanation check.")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    args = parser.parse_args()

    report = run_explanation_check()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
