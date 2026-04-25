"""Azure OpenAI provider — the enterprise target at UBS.

Requires `openai>=1.40` and: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT.
Import is lazy so Sherlock still boots without the lib installed.
"""

from app.config import settings
from app.llm.base import LLMResponse


class AzureOpenAIProvider:
    name = "azure_openai"

    def __init__(self, deployment: str | None = None) -> None:
        try:
            from openai import AzureOpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "openai SDK not installed. `pip install openai>=1.40` or switch "
                "SHERLOCK_LLM_PROVIDER to mock/gemini."
            ) from exc
        if not (settings.azure_openai_endpoint and settings.azure_openai_api_key):
            raise RuntimeError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set.")
        self.model = deployment or settings.azure_openai_deployment or "gpt-5.1"
        self._client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version or "2024-06-01",
        )

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=text, model=self.model, provider=self.name,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
