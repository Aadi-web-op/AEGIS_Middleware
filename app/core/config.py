import os
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from app.core.scoring import ScoringWeights
from app.schemas import Decision


class UnknownProfileError(ValueError):
    """Raised when a request asks for a risk profile that isn't configured."""


class Thresholds(BaseModel):
    answer: float
    caveat: float
    escalate: float

    @model_validator(mode="after")
    def must_be_ordered(self):
        if not (1.0 >= self.answer > self.caveat > self.escalate >= 0.0):
            raise ValueError("thresholds must satisfy 1 >= answer > caveat > escalate >= 0")
        return self


class Vetoes(BaseModel):
    abstain_below_relevance: float
    escalate_above_contradiction: float
    escalate_below_support: float
    caveat_below_freshness: float
    escalate_above_ambiguity: float


class ClaimVetoes(BaseModel):
    """Claim-level rules. They act on individual claims, not on the average.

    A claim is *grounded* when at least `min_grounding` of its content words
    appear in one evidence passage: the documents talk about it even though
    the entailment model could not confirm it. An *ungrounded* unsupported
    claim is one the documents do not mention at all.
    """

    # Least cautious decision allowed when any claim is not SUPPORTED.
    unsupported_floor: Decision = Decision.CAVEAT
    # Least cautious decision allowed when any claim is CONTRADICTED.
    contradicted_floor: Decision = Decision.ESCALATE
    # ESCALATE when at least this share of the claims is unsupported and
    # ungrounded. None disables the rule.
    escalate_at_ungrounded_fraction: float | None = None
    # ABSTAIN when no claim is supported and none is even grounded: the
    # documents do not contain what the answer says.
    abstain_when_none_supported: bool = True
    min_grounding: float = 0.5


class ProfileConfig(BaseModel):
    description: str = ""
    thresholds: Thresholds
    vetoes: Vetoes
    claims: ClaimVetoes = ClaimVetoes()
    answer_min_signal: float | None = None


class PolicyConfig(BaseModel):
    version: str
    weights: ScoringWeights = ScoringWeights()
    profiles: dict[str, ProfileConfig]

    def get_profile(self, name: str) -> ProfileConfig:
        try:
            return self.profiles[name]
        except KeyError:
            available = ", ".join(sorted(self.profiles))
            raise UnknownProfileError(
                f"Unknown profile '{name}'. Available: {available}"
            ) from None


def default_policy_path() -> Path:
    override = os.environ.get("AEGIS_POLICY_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "config" / "policy.yaml"


def load_policy_config(path: str | Path | None = None) -> PolicyConfig:
    file_path = Path(path) if path else default_policy_path()
    with open(file_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return PolicyConfig.model_validate(raw)
    