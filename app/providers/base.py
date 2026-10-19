from abc import ABC, abstractmethod

from pydantic import BaseModel


class ProviderError(Exception):
    """An LLM provider could not produce a usable answer."""


class LLMResponse(BaseModel):
    text: str
    provider: str
    fallback_used: bool = False


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> LLMResponse:
        """Send a prompt to an LLM and return its reply."""
        ...
        