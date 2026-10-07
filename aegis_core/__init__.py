"""AEGIS - Open-Source Uncertainty Middleware for AI Systems.

This package contains the Evidence Intelligence Engine subsystem.
"""

__version__ = "0.1.0"

from aegis_core.evidence import EvidenceEngine, EvidenceResult, create_evidence_engine

__all__ = ["EvidenceEngine", "EvidenceResult", "create_evidence_engine"]
