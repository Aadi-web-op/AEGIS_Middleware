"""Unit tests for Calibration (Feature #5) and Auditor Export (Feature #7).

Per "AEGIS Finale Plan: Decisions & Task Split" (Nov 17, 2026):
- Calibration and empirical band
- Auditor export
"""

from __future__ import annotations

import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from app.audit.export import build_auditor_report, format_report_markdown
from app.audit.logger import AuditLogger
from app.core.calibration import (
    BANDS,
    compute_calibration_from_cases,
    find_band_for_score,
    get_calibration_for_score,
    get_calibration_summary,
)
from app.core.evaluator import Evaluator
from app.escalation.queue import EscalationQueue
from app.evidence.stubs import FixedSignal
from app.main import create_app


# ---------------------------------------------------------------------------
# Calibration Unit Tests
# ---------------------------------------------------------------------------

def test_find_band_for_score_boundaries():
    """Verify band classification covers the [0.0, 1.0] interval correctly."""
    assert find_band_for_score(0.0)["band_id"] == "low"
    assert find_band_for_score(0.25)["band_id"] == "low"
    assert find_band_for_score(0.40)["band_id"] == "moderate"
    assert find_band_for_score(0.55)["band_id"] == "moderate"
    assert find_band_for_score(0.65)["band_id"] == "good"
    assert find_band_for_score(0.80)["band_id"] == "good"
    assert find_band_for_score(0.85)["band_id"] == "high"
    assert find_band_for_score(1.0)["band_id"] == "high"

    # Clamping
    assert find_band_for_score(-0.5)["band_id"] == "low"
    assert find_band_for_score(1.5)["band_id"] == "high"


def test_get_calibration_for_score_message_and_n():
    """Verify calibration statement honestly shows correct X and sample size N."""
    high_cal = get_calibration_for_score(0.92)
    assert high_cal["band_id"] == "high"
    assert high_cal["sample_size"] == 2
    assert high_cal["correct_count"] == 2
    assert "2 of 2 times" in high_cal["message"]
    assert "N=2" in high_cal["message"]
    assert high_cal["empirical_accuracy"] == 1.0
    assert "not an uncalibrated model probability" in high_cal["disclaimer"]

    mod_cal = get_calibration_for_score(0.50)
    assert mod_cal["band_id"] == "moderate"
    assert mod_cal["sample_size"] == 4
    assert mod_cal["correct_count"] == 3
    assert "3 of 4 times" in mod_cal["message"]
    assert "N=4" in mod_cal["message"]
    assert mod_cal["empirical_accuracy"] == 0.75


def test_get_calibration_summary_structure():
    """Verify calibration summary provides transparency across all bands."""
    summary = get_calibration_summary()
    assert summary["total_dev_samples"] == 12
    assert summary["total_dev_correct"] >= 10
    assert len(summary["bands"]) == 4
    for b in summary["bands"]:
        assert "sample_size" in b
        assert "correct_count" in b
        assert "empirical_accuracy" in b
        assert "label" in b


# ---------------------------------------------------------------------------
# Auditor Export Unit Tests
# ---------------------------------------------------------------------------

def test_build_auditor_report_fallback():
    """Verify report builder produces complete compliance structure even without db record."""
    report = build_auditor_report("test-req-001")
    assert report["report_id"] == "AUDIT-test-req-001"
    assert "generated_at" in report
    assert "request" in report
    assert "evaluation" in report
    assert "empirical_calibration" in report["evaluation"]
    assert "signals" in report
    assert report["auditor_attestation"]["fail_closed_guarantee"] is True


def test_format_report_markdown():
    """Verify report formats into clean GitHub-flavored markdown."""
    report = build_auditor_report("test-req-002")
    md = format_report_markdown(report)
    assert "# AEGIS Compliance & Audit Report: `test-req-002`" in md
    assert "## 1. Executive Summary" in md
    assert "## 3. Signal Breakdown" in md
    assert "## 5. Attestation & Governance" in md


# ---------------------------------------------------------------------------
# API Integration Tests for Calibration & Export
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_with_audit_db(tmp_path):
    audit_db = str(tmp_path / "test_audit_export.db")
    esc_db = str(tmp_path / "test_esc_export.db")

    audit = AuditLogger(db_path=audit_db)
    esc_q = EscalationQueue(db_path=esc_db)

    signals_vals = {
        "relevance": 0.9, "entailment": 0.88, "contradiction": 0.08,
        "freshness": 0.92, "completeness": 0.85, "ambiguity": 0.05,
    }
    evaluator = Evaluator([FixedSignal(k, v) for k, v in signals_vals.items()])
    app = create_app(evaluator=evaluator, audit_logger=audit, escalation_queue=esc_q)
    app.state.audit_db_path = audit_db
    app.state.escalations_db_path = esc_db

    # Seed an audit record
    conn = sqlite3.connect(audit_db)
    conn.execute(
        """
        INSERT INTO audit_logs
            (request_id, timestamp, query, answer, profile,
             decision, answerability_score, signals, reason_codes,
             generation_success, error_message, latency_ms)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "req-compliance-101", "2026-11-18T10:00:00Z",
            "What is the casual leave policy?", "Employees get 18 casual leaves.", "standard",
            "ANSWER", 0.91,
            json.dumps(signals_vals),
            json.dumps([]),
            1, None, 45.0,
        ),
    )
    conn.commit()
    conn.close()

    return TestClient(app)


def test_api_calibration_endpoint(client_with_audit_db):
    """Test GET /v1/insights/calibration with score query param."""
    resp = client_with_audit_db.get("/v1/insights/calibration?score=0.91")
    assert resp.status_code == 200
    data = resp.json()
    assert data["band_id"] == "high"
    assert "2 of 2 times" in data["message"]

    summary_resp = client_with_audit_db.get("/v1/insights/calibration")
    assert summary_resp.status_code == 200
    summary_data = summary_resp.json()
    assert "bands" in summary_data


def test_api_export_json_endpoint(client_with_audit_db):
    """Test GET /v1/insights/export/{request_id} returning JSON audit report."""
    resp = client_with_audit_db.get("/v1/insights/export/req-compliance-101")
    assert resp.status_code == 200
    data = resp.json()
    assert data["report_id"] == "AUDIT-req-compliance-101"
    assert data["request"]["query"] == "What is the casual leave policy?"
    assert data["evaluation"]["decision"] == "ANSWER"
    assert data["evaluation"]["empirical_calibration"]["dev_set_samples_n"] == 2


def test_api_export_markdown_endpoint(client_with_audit_db):
    """Test GET /v1/insights/export/{request_id}?format=markdown returning markdown."""
    resp = client_with_audit_db.get("/v1/insights/export/req-compliance-101?format=markdown&download=true")
    assert resp.status_code == 200
    assert "attachment; filename=\"aegis_audit_req-compliance-101.md\"" in resp.headers.get("Content-Disposition", "")
    assert "# AEGIS Compliance & Audit Report: `req-compliance-101`" in resp.text


def test_api_impacted_decisions_endpoint(client_with_audit_db):
    """Test GET /v1/insights/impacted-decisions blast-radius endpoint."""
    resp = client_with_audit_db.get("/v1/insights/impacted-decisions?source=hr-policy.pdf&version=2024.2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "hr-policy.pdf"
    assert data["version"] == "2024.2"
    assert "total_affected_decisions" in data
