from app.providers.base import LLMProvider, LLMResponse, ProviderError


class FakeProvider(LLMProvider):
    """A scripted provider for tests and offline development."""

    def __init__(self, responses: list[str] | None = None, name: str = "fake", fail: bool = False):
        self.name = name
        self._responses = list(responses) if responses else ["ok"]
        self._fail = fail
        self._next = 0
        self.prompts: list[str] = []

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> LLMResponse:
        self.prompts.append(prompt)
        if self._fail:
            raise ProviderError(f"{self.name}: simulated failure")
        text = self._responses[min(self._next, len(self._responses) - 1)]
        self._next += 1
        return LLMResponse(text=text, provider=self.name)
        