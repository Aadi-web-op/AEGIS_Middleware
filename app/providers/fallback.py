import logging

from app.providers.base import LLMProvider, LLMResponse, ProviderError

logger = logging.getLogger(__name__)


class FallbackProvider(LLMProvider):
    """Tries providers in order; the first one that works wins."""

    def __init__(self, providers: list[LLMProvider]):
        if not providers:
            raise ValueError("FallbackProvider needs at least one provider")
        self.providers = providers
        self.name = "fallback(" + ",".join(p.name for p in providers) + ")"

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> LLMResponse:
        errors: list[str] = []
        for index, provider in enumerate(self.providers):
            try:
                result = provider.generate(
                    prompt, system=system, temperature=temperature, max_tokens=max_tokens
                )
            except ProviderError as exc:
                logger.warning("Provider %s failed: %s", provider.name, exc)
                errors.append(str(exc))
                continue
            return result.model_copy(update={"fallback_used": index > 0})
        raise ProviderError("All providers failed: " + "; ".join(errors))
        