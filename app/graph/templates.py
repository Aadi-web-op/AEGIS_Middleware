"""Plain-language explanation templates for the Aegis Decision Graph.

Implements the fixed explanation templates specified in:
"Aegis Decision Graph (Neo4j Add-on): Team Brief" (Oct 22, 2026), Section 5.

Every sentence comes from a fixed template, not from an LLM, ensuring
zero latency overhead, deterministic output, and zero hallucination risk.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.schemas import Decision, ReasonCode

# Headlines for each decision outcome
HEADLINES: Dict[str, str] = {
    Decision.ANSWER.value: "Safe to show. Every statement in the answer is backed by current documents.",
    Decision.CAVEAT.value: "Mostly backed up, but something needs a warning.",
    Decision.ESCALATE.value: "A person should check this before anyone relies on it.",
    Decision.ABSTAIN.value: "We could not find enough in your documents to answer.",
}

# Templates for each reason code
REASON_TEMPLATES: Dict[str, str] = {
    ReasonCode.NO_EVIDENCE.value: "We found nothing in your documents about this.",
    ReasonCode.LOW_RELEVANCE.value: "The documents we found are about something else.",
    ReasonCode.UNSUPPORTED_CLAIM.value: 'The answer says "{claim}", but no document backs that up.',
    ReasonCode.CONTRADICTION.value: "{doc_a} says {val_a}, but {doc_b} says {val_b}.",
    ReasonCode.STALE_EVIDENCE.value: "The only source is {doc} ({version}, {date}). A newer version may exist.",
    ReasonCode.INCOMPLETE_EVIDENCE.value: "The documents cover only part of the question: {missing_part}.",
    ReasonCode.AMBIGUOUS_QUERY.value: "The question could mean more than one thing. {clarifying_question}",
    ReasonCode.SIGNAL_UNAVAILABLE.value: "One of our checks could not run, so we took the cautious route.",
}


def render_headline(decision: Decision | str) -> str:
    """Return the plain-language headline for a decision."""
    val = decision.value if isinstance(decision, Decision) else str(decision)
    return HEADLINES.get(val, "Decision returned by Aegis.")


def render_reason(code: ReasonCode | str, params: Optional[Mapping[str, Any]] = None) -> str:
    """Format the plain-language sentence for a reason code with provided parameters."""
    val = code.value if isinstance(code, ReasonCode) else str(code)
    template = REASON_TEMPLATES.get(val)
    if not template:
        return "Uncertainty detected in the available evidence."

    params = params or {}
    try:
        # Default fallbacks if parameters are missing
        safe_params = {
            "claim": params.get("claim", "this claim"),
            "doc_a": params.get("doc_a", "Source A"),
            "val_a": params.get("val_a", "one value"),
            "doc_b": params.get("doc_b", "Source B"),
            "val_b": params.get("val_b", "a different value"),
            "doc": params.get("doc", "the document"),
            "version": params.get("version", "v1"),
            "date": params.get("date", "undated"),
            "missing_part": params.get("missing_part", "additional details"),
            "clarifying_question": params.get("clarifying_question", "Could you add more detail?"),
        }
        return template.format(**safe_params)
    except Exception:
        return template
