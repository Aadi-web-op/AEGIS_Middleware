import os
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from app.core.scoring import ScoringWeights


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


class ProfileConfig(BaseModel):
    description: str = ""
    thresholds: Thresholds
    vetoes: Vetoes
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
    