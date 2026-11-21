"""FastAPI HTTP interface for the AEGIS Evidence Intelligence Engine.

Developer-facing, Stripe/API-gateway style:

    POST /v1/evaluate
    {
        "query": "...",
        "answer": "...",
        "evidence": ["...", "..."]
    }

Returns the four evidence signals plus reasons and diagnostics.
The final ANSWER/CAVEAT/ESCALATE/ABSTAIN decision is made by the
central AEGIS policy engine, which consumes this output.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from aegis_core.evidence.engine import EvidenceEngine

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------
class EvidenceItem(BaseModel):
    """A single evidence passage, optionally with metadata."""
    text: str
    source: Optional[str] = None
    version: Optional[str] = None
    date: Optional[str] = None


class EvaluateRequest(BaseModel):
    """Request body for /v1/evaluate."""
    query: str
    answer: str
    evidence: List[Any] = Field(default_factory=list)
    """List of strings or EvidenceItem objects."""


class SignalResponse(BaseModel):
    """One signal's result."""
    value: float
    reasons: List[str]
    details: Dict[str, Any]


class EvaluateResponse(BaseModel):
    """Response body for /v1/evaluate.

    NOTE: this contains evidence signals only. The `decision`
    field (ANSWER/CAVEAT/ESCALATE/ABSTAIN) is added downstream by
    the central AEGIS policy engine.
    """
    decision_ready: bool
    signals: Dict[str, SignalResponse]
    reasons: List[str]
    timing_ms: Dict[str, float]
    metadata: Dict[str, Any]


# ------------------------------------------------------------------
# App factory
# ------------------------------------------------------------------
def create_app(engine: Optional[EvidenceEngine] = None):
    """Create the FastAPI app. Kept importable without Uvicorn."""
    from fastapi import FastAPI

    app = FastAPI(
        title="AEGIS Evidence Intelligence",
        version="0.1.0",
        description=(
            "Model-agnostic uncertainty middleware. Produces evidence "
            "signals (relevance, entailment, contradiction, completeness) "
            "that the central AEGIS policy engine turns into "
            "ANSWER/CAVEAT/ESCALATE/ABSTAIN."
        ),
    )
    state_engine = engine or EvidenceEngine()

    @app.get("/health")
    def health():
        return {"status": "ok", "subsystem": "evidence-intelligence"}

    @app.post("/v1/evaluate", response_model=EvaluateResponse)
    def evaluate(req: EvaluateRequest):
        # Accept plain strings or EvidenceItem objects.
        texts: List[str] = []
        metadata: List[Dict[str, Any]] = []
        for item in req.evidence:
            if isinstance(item, EvidenceItem):
                texts.append(item.text)
                metadata.append(
                    {
                        "source": item.source,
                        "version": item.version,
                        "date": item.date,
                    }
                )
            elif isinstance(item, dict):
                texts.append(str(item.get("text", "")))
                metadata.append(
                    {
                        "source": item.get("source"),
                        "version": item.get("version"),
                        "date": item.get("date"),
                    }
                )
            else:
                texts.append(str(item))

        has_metadata = any(m.get("source") or m.get("version") for m in metadata)

        result = state_engine.evaluate(
            query=req.query,
            answer=req.answer,
            evidence=texts,
            evidence_metadata=metadata if has_metadata else None,
        )

        return EvaluateResponse(
            decision_ready=result.decision_ready,
            signals={
                name: SignalResponse(
                    value=body["value"],
                    reasons=body["reasons"],
                    details=body["details"],
                )
                for name, body in result.signals.items()
            },
            reasons=result.reasons,
            timing_ms=result.timing_ms,
            metadata=result.metadata,
        )

    return app


# Module-level app for `uvicorn aegis_core.api:app`
app = create_app()
