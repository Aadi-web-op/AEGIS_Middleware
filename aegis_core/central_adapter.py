"""Integration contract between Evidence Intelligence and the central AEGIS evaluator.

OWNERSHIP BOUNDARY
------------------
This subsystem (Evidence Intelligence) produces *signals* only.
It does NOT decide ANSWER / CAVEAT / ESCALATE / ABSTAIN and does
NOT compute an "answerability_score". Those belong to the central
AEGIS uncertainty/policy engine (owned by another teammate).

CONTRACT
--------
The central policy engine consumes a dict of the form:

    {
        "query": str,
        "answer": str,
        "signals": {
            "relevance":     {"value": float, "reasons": [str], "details": {...}},
            "entailment":    {...},
            "contradiction": {...},
            "completeness":  {...},
        },
        "reasons": [str],
        "metadata": {...},
    }

and adds:

    {
        "decision": "ANSWER" | "CAVEAT" | "ESCALATE" | "ABSTAIN",
        "answerability_score": float,
        ...
    }

The decision labels are exactly these four. There is no CLARIFY;
a clarifying question is an *action* inside ESCALATE.
"""

import logging
from typing import Any, Dict, Optional, List

from aegis_core import EvidenceEngine
from aegis_core.evidence.engine import EvidenceResult

logger = logging.getLogger(__name__)

# The four decisions the central engine may emit. Documented here
# for contract clarity only - this subsystem never selects one.
DECISIONS = ("ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN")


class CentralAegisAdapter:
    """
    Bridges the Evidence Intelligence Engine and the central
    AEGIS policy engine.

    Usage by the central engine:

        adapter = CentralAegisAdapter()
        payload = adapter.run(query, answer, evidence)
        # payload["signals"] -> feed to your policy engine
        # your policy engine sets payload["decision"]
    """

    def __init__(self, engine: Optional[EvidenceEngine] = None):
        self.engine = engine or EvidenceEngine()

    def run(
        self,
        query: str,
        answer: str,
        evidence: List[str],
        evidence_metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Produce the signal payload the central policy engine needs.

        Returns a dict with query/answer/signals/reasons/metadata.
        The caller (central engine) is responsible for adding the
        final "decision" and "answerability_score".
        """
        result: EvidenceResult = self.engine.evaluate(
            query=query,
            answer=answer,
            evidence=evidence,
            evidence_metadata=evidence_metadata,
        )
        return self.to_policy_payload(query, answer, result)

    @staticmethod
    def to_policy_payload(
        query: str, answer: str, result: EvidenceResult
    ) -> Dict[str, Any]:
        """Convert an EvidenceResult into the policy-engine payload."""
        return {
            "query": query,
            "answer": answer,
            "signals": {
                name: {
                    "value": body["value"],
                    "reasons": body["reasons"],
                    "details": body["details"],
                }
                for name, body in result.signals.items()
            },
            "reasons": result.reasons,
            "metadata": result.metadata,
        }


def evaluate_for_policy(
    query: str,
    answer: str,
    evidence: List[str],
    evidence_metadata: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Convenience function for the central AEGIS evaluator."""
    return CentralAegisAdapter().run(
        query, answer, evidence, evidence_metadata
    )
