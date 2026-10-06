from app.evidence.base import Signal
from app.schemas import EvidenceItem, Reason, ReasonCode, SignalResult


class AmbiguitySignal(Signal):
    """Estimate how ambiguous the user's query is.

    Returns:
        0.0 = clear query
        1.0 = highly ambiguous query
    """

    name = "ambiguity"

    def score(
        self,
        query: str,
        answer: str,
        evidence: list[EvidenceItem],
    ) -> SignalResult:

        query = query.strip()

        if not query:
            return SignalResult(
                value=1.0,
                reasons=[
                    Reason(
                        code=ReasonCode.AMBIGUOUS_QUERY,
                        message="The query is empty and cannot be interpreted reliably.",
                    )
                ],
                details={"reason": "empty_query"},
            )

        words = query.split()

        ambiguity = 0.0
        reasons = []

        # Very short queries often lack enough context.
        if len(words) <= 2:
            ambiguity += 0.5
            reasons.append(
                Reason(
                    code=ReasonCode.AMBIGUOUS_QUERY,
                    message="The query is very short and may lack sufficient context.",
                )
            )

        # Generic question words without a clear subject.
        generic_terms = {
            "what",
            "why",
            "how",
            "it",
            "this",
            "that",
            "they",
            "them",
        }

        generic_count = sum(
            1 for word in words
            if word.lower().strip(".,?!") in generic_terms
        )

        if generic_count >= 2:
            ambiguity += 0.3
            reasons.append(
                Reason(
                    code=ReasonCode.AMBIGUOUS_QUERY,
                    message="The query contains multiple generic or context-dependent terms.",
                )
            )

        ambiguity = min(ambiguity, 1.0)

        return SignalResult(
            value=round(ambiguity, 4),
            reasons=reasons,
            details={
                "word_count": len(words),
                "generic_term_count": generic_count,
            },
        )
