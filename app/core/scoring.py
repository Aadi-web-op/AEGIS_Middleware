from pydantic import BaseModel, Field, model_validator

from app.schemas import Signals


class ScoringWeights(BaseModel):
    """How much each term counts. Defaults come from the team plan (Section 8.1)."""

    relevance: float = Field(default=0.25, ge=0.0)
    support: float = Field(default=0.25, ge=0.0)
    agreement: float = Field(default=0.15, ge=0.0)
    freshness: float = Field(default=0.10, ge=0.0)
    completeness: float = Field(default=0.15, ge=0.0)
    clarity: float = Field(default=0.10, ge=0.0)

    @model_validator(mode="after")
    def weights_must_sum_to_one(self):
        total = sum(self.model_dump().values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0, got {total:.4f}")
        return self


class ScoreResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    contributions: dict[str, float]
    unavailable: list[str]


# (term in the formula, signal it comes from, flip it with 1 - value?)
_TERMS = [
    ("relevance", "relevance", False),
    ("support", "entailment", False),
    ("agreement", "contradiction", True),
    ("freshness", "freshness", False),
    ("completeness", "completeness", False),
    ("clarity", "ambiguity", True),
]


def compute_score(signals: Signals, weights: ScoringWeights | None = None) -> ScoreResult:
    if weights is None:
        weights = ScoringWeights()

    total = 0.0
    contributions: dict[str, float] = {}
    unavailable: list[str] = []

    for term, signal_name, inverted in _TERMS:
        raw = getattr(signals, signal_name)
        if raw is None:
            unavailable.append(signal_name)
            goodness = 0.0
        else:
            goodness = 1.0 - raw if inverted else raw

        part = getattr(weights, term) * goodness
        contributions[term] = round(part, 4)
        total += part

    total = round(min(max(total, 0.0), 1.0), 4)
    return ScoreResult(score=total, contributions=contributions, unavailable=unavailable)
    