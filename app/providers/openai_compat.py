
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

        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

        self._client = (
            client
            if client is not None
            else httpx.Client(timeout=timeout_s)
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
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = self._client.post(
                self._url,
                json=body,
                headers=self._headers,
            )
            response.raise_for_status()

            text = response.json()["choices"][0]["message"]["content"]

        except httpx.HTTPStatusError as exc:
            # Preserve the provider's explanation for debugging.
            try:
                error_body = exc.response.json()
                if isinstance(error_body, dict):
                    error_info = error_body.get("error", {})
                    if isinstance(error_info, dict):
                        detail = error_info.get("message")
                    else:
                        detail = str(error_info) if error_info else None
                else:
                    detail = None
            except ValueError:
                detail = None

            if not detail:
                detail = exc.response.text[:500] or "No error details returned"

            raise ProviderError(
                f"{self.name}: HTTP {exc.response.status_code}: {detail}"
            ) from exc

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
