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
    ReasonCode.LOCKED_FACT_MISMATCH.value: "The answer contradicts a fact your company locked.",
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


# Opening sentence of `explanation.summary`, per decision.
SUMMARY_LEADS: Dict[str, str] = {
    Decision.ANSWER.value: "The answer can be shown as it is.",
    Decision.CAVEAT.value: "The answer can be shown, but with a warning.",
    Decision.ESCALATE.value: "The answer should not be shown until a person has checked it.",
    Decision.ABSTAIN.value: "The answer should not be shown: the documents do not back it.",
}


def render_summary(
    decision: Decision | str,
    decisive_rule: Optional[str],
    factors: Optional[List[Any]] = None,
) -> str:
    """One to three plain sentences saying why this decision was made.

    Built only from fixed wording plus the messages of the measured factors,
    so it can never say more than the policy engine actually found.
    `factors` are `ExplanationFactor` objects (or dicts of the same shape).
    """
    val = decision.value if isinstance(decision, Decision) else str(decision)
    lead = SUMMARY_LEADS.get(val, "Decision returned by Aegis.")

    def field(factor: Any, name: str) -> Any:
        return factor.get(name) if isinstance(factor, Mapping) else getattr(factor, name, None)

    def effect_of(factor: Any) -> Optional[str]:
        effect = field(factor, "effect")
        return effect.value if isinstance(effect, Decision) else (str(effect) if effect else None)

    factors = list(factors or [])
    if not factors:
        return lead

    score = next((f for f in factors if field(f, "signal") == "answerability_score"), None)
    rules = [f for f in factors if f is not score]

    if val == Decision.ANSWER.value:
        detail = field(score, "message") if score is not None else None
        tail = " No check raised a concern." if not rules else ""
        return f"{lead} {detail}{tail}" if detail else lead

    # The factor that forced this decision comes first; the rest are counted.
    decisive = [f for f in rules if effect_of(f) == val]
    if decisive_rule == "score_threshold" or not decisive:
        main = field(score, "message") if score is not None else None
        others = len(rules)
    else:
        main = field(decisive[0], "message")
        others = len(rules) - 1

    parts = [lead]
    if main:
        parts.append(main)
    if others > 0:
        noun = "check also raised a concern" if others == 1 else "checks also raised concerns"
        parts.append(f"{others} other {noun}.")
    return " ".join(parts)
