"""Unit tests for explanation templates and the 20-case explanation check.

Tests verify template rendering and explanation faithfulness checking.
"""

from __future__ import annotations

import pytest

from app.core.evaluator import Evaluator
from app.evidence.stubs import FixedSignal
from app.graph.templates import (
    HEADLINES,
    REASON_TEMPLATES,
    render_headline,
    render_reason,
)
from app.schemas import Decision, ReasonCode
from scripts.explanation_check import run_explanation_check
from tests.benchmark.test_cases import BENCHMARK_CASES


def test_headline_templates_cover_all_decisions():
    """Verify that every decision has a clear, non-empty plain-language headline."""
    for decision in Decision:
        headline = render_headline(decision)
        assert headline
        assert headline == HEADLINES[decision.value]


def test_reason_templates_cover_all_reason_codes():
    """Verify that every defined reason code has a corresponding template sentence."""
    for code in ReasonCode:
        template = render_reason(code)
        assert template
        assert len(template) > 10


def test_template_rendering_fills_parameters():
    """Verify parameters are interpolated cleanly into explanation templates."""
    rendered = render_reason(
        ReasonCode.CONTRADICTION,
        {"doc_a": "policy_2026", "val_a": "18", "doc_b": "circular_2025", "val_b": "12"},
    )
    assert "policy_2026 says 18, but circular_2025 says 12." in rendered


def test_explanation_check_evaluates_20_cases():
    """Verify that run_explanation_check evaluates all 20 cases and computes honest metrics."""
    signals = [
        FixedSignal("relevance", 0.9),
        FixedSignal("entailment", 0.85),
        FixedSignal("contradiction", 0.05),
        FixedSignal("freshness", 0.95),
        FixedSignal("completeness", 0.9),
        FixedSignal("ambiguity", 0.05),
    ]
    evaluator = Evaluator(signals)

    report = run_explanation_check(cases=BENCHMARK_CASES, evaluator=evaluator)

    assert report["total_cases"] == 20
    assert 0.0 <= report["headline_accuracy"] <= 100.0
    assert 0.0 <= report["reason_accuracy"] <= 100.0
    assert len(report["cases"]) == 20

    for c in report["cases"]:
        assert "headline_match" in c
        assert "reason_match" in c
        assert "failure_type" in c
