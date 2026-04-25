"""LLM provider factory — one entry point, env-var driven."""

import logging

from app.config import settings
from app.llm.base import LLMProvider
from app.llm.mock import MockLLMProvider

log = logging.getLogger("sherlock.llm")


def get_llm() -> LLMProvider:
    """Return the provider named by `SHERLOCK_LLM_PROVIDER`, falling back to mock."""
    provider = (settings.llm_provider or "mock").lower()

    if provider == "mock":
        return MockLLMProvider()

    if provider == "gemini":
        try:
            from app.llm.gemini import GeminiProvider
            return GeminiProvider()
        except Exception:
            log.exception("gemini provider failed to initialize — falling back to mock")
            return MockLLMProvider()

    if provider == "azure_openai":
        try:
            from app.llm.azure_openai import AzureOpenAIProvider
            return AzureOpenAIProvider()
        except Exception:
            log.exception("azure_openai provider failed to initialize — falling back to mock")
            return MockLLMProvider()

    log.warning("unknown SHERLOCK_LLM_PROVIDER=%r — falling back to mock", provider)
    return MockLLMProvider()
