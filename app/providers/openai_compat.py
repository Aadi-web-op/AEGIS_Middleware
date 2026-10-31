
import httpx

from app.providers.base import LLMProvider, LLMResponse, ProviderError


class OpenAICompatibleProvider(LLMProvider):
    """Talks to any server that speaks the OpenAI /chat/completions format
    (Ollama, Groq, Gemini's compatibility endpoint, OpenAI, ...)."""

    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self.name = name
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Content-Type": "application/json"}
        self._api_key = api_key.strip().strip('"').strip("'") if api_key else None

        if self._api_key:
            self._headers["Authorization"] = f"Bearer {self._api_key}"

        self._client = (
            client
            if client is not None
            else httpx.Client(timeout=timeout_s)
        )

    @staticmethod
    def _requires_max_completion_tokens(model: str) -> bool:
        lowered = model.lower()
        return (
            "gpt-oss" in lowered
            or lowered.startswith("o1")
            or lowered.startswith("o3")
            or "deepseek-r1" in lowered
        )

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> LLMResponse:
        messages = []

        if system:
            messages.append({"role": "system", "content": system})

        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
        }

        if self._requires_max_completion_tokens(self.model):
            body["max_completion_tokens"] = max(max_tokens, 2048)
            body["temperature"] = 1e-8 if temperature == 0.0 else temperature
        else:
            body["temperature"] = temperature
            body["max_tokens"] = max_tokens

        try:
            response = self._client.post(
                self._url,
                json=body,
                headers=self._headers,
            )
            response.raise_for_status()

            text = response.json()["choices"][0]["message"]["content"]

        except httpx.HTTPStatusError as exc:
            detail = None
            try:
                error_body = exc.response.json()
                if isinstance(error_body, dict):
                    error_info = error_body.get("error", {})
                    if isinstance(error_info, dict):
                        detail = error_info.get("message")
                    elif isinstance(error_info, str):
                        detail = error_info
                    elif "message" in error_body and isinstance(error_body["message"], str):
                        detail = error_body["message"]
                    elif "detail" in error_body and isinstance(error_body["detail"], str):
                        detail = error_body["detail"]
            except (ValueError, TypeError):
                detail = None

            if self._api_key and detail and self._api_key in detail:
                detail = detail.replace(self._api_key, "[REDACTED]")

            msg = f"{self.name}: HTTP {exc.response.status_code}"
            if detail:
                msg += f": {detail}"

            raise ProviderError(msg) from exc

        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.name}: request failed ({type(exc).__name__})"
            ) from exc

        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(
                f"{self.name}: unexpected response format"
            ) from exc

        if not isinstance(text, str) or not text.strip():
            raise ProviderError(f"{self.name}: empty response")

        return LLMResponse(
            text=text.strip(),
            provider=self.name,
        )
