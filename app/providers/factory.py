import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.providers.base import LLMProvider, ProviderError
from app.providers.fallback import FallbackProvider
from app.providers.openai_compat import OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class ProviderSpec(BaseModel):
    name: str
    base_url: str
    model: str
    api_key_env: str | None = None
    timeout_s: float = Field(default=30.0, gt=0)


class ProvidersConfig(BaseModel):
    chain: list[ProviderSpec] = Field(min_length=1)


def default_providers_path() -> Path:
    override = os.environ.get("AEGIS_PROVIDERS_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "config" / "providers.yaml"


def load_providers_config(path: str | Path | None = None) -> ProvidersConfig:
    file_path = Path(path) if path else default_providers_path()
    with open(file_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ProvidersConfig.model_validate(raw)


def build_provider(config: ProvidersConfig | None = None) -> LLMProvider:
    """Turn the YAML chain into one ready-to-use provider."""
    config = config if config is not None else load_providers_config()
    providers: list[LLMProvider] = []

    for spec in config.chain:
        if spec.model.startswith("REPLACE"):
            logger.warning("Skipping %s: model name is still a placeholder", spec.name)
            continue
        api_key = None
        if spec.api_key_env:
            api_key = os.environ.get(spec.api_key_env)
            if not api_key:
                logger.warning("Skipping %s: environment variable %s is not set",
                               spec.name, spec.api_key_env)
                continue
        providers.append(OpenAICompatibleProvider(
            name=spec.name, base_url=spec.base_url, model=spec.model,
            api_key=api_key, timeout_s=spec.timeout_s,
        ))

    if not providers:
        raise ProviderError(
            "No usable LLM provider. Edit config/providers.yaml and set the API-key variables."
        )
    return providers[0] if len(providers) == 1 else FallbackProvider(providers)
    