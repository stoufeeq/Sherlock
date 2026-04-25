"""LLMProvider — the minimal interface Sherlock uses to call a language model.

Implementations live alongside this file (mock.py, gemini.py, azure_openai.py).
Nothing outside `app/llm/` should import a specific provider directly — go through
`factory.get_llm()` so swapping providers is one env-var change.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """One-shot completion."""
        ...
