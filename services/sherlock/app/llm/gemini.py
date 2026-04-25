"""Google Gemini provider — used for local dev at UBS-adjacent environments.

Requires `google-generativeai` in requirements and a valid `GEMINI_API_KEY` in env.
Import is lazy so Sherlock still boots when the lib isn't installed.
"""

from app.config import settings
from app.llm.base import LLMResponse


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str | None = None) -> None:
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "google-generativeai not installed. `pip install google-generativeai` "
                "or switch SHERLOCK_LLM_PROVIDER to mock/azure_openai."
            ) from exc
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        genai.configure(api_key=settings.gemini_api_key)
        self.model = model or settings.gemini_model or "gemini-1.5-flash"
        self._client = genai.GenerativeModel(self.model)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> LLMResponse:
        import logging
        log = logging.getLogger("sherlock.llm.gemini")

        full = prompt if not system else f"{system}\n\n{prompt}"
        resp = self._client.generate_content(
            full,
            generation_config={"max_output_tokens": max_tokens, "temperature": temperature},
        )
        # Gemini 2.x returns partial output with finish_reason=MAX_TOKENS (=2) when
        # thinking tokens eat the budget. Log that so the operator can tune it.
        try:
            for c in resp.candidates or []:
                fr = getattr(c, "finish_reason", None)
                if fr and int(fr) == 2:
                    log.warning(
                        "gemini response truncated (finish_reason=MAX_TOKENS, budget=%d). "
                        "Consider raising max_tokens or using a non-reasoning model.",
                        max_tokens,
                    )
        except Exception:
            pass
        return LLMResponse(text=resp.text or "", model=self.model, provider=self.name)
