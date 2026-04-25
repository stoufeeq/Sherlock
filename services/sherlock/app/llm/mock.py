"""Deterministic, no-API-key mock LLM.

Useful for local dev before anyone wires up Gemini/Azure OpenAI, and for the
CI pipeline (so autodoc tests don't burn tokens). The mock returns a structured
stub response that still produces a usable README — the autodoc generator does
most of the work deterministically from the graph anyway; the LLM pass is only
expected to polish prose.
"""

from app.llm.base import LLMResponse


class MockLLMProvider:
    name = "mock"
    model = "mock-v1"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> LLMResponse:
        # Hints the autodoc generator uses to ask for specific short outputs.
        # A real LLM would synthesize prose; the mock echoes a sensible skeleton
        # so the README still looks coherent.
        if "one-sentence purpose" in prompt.lower():
            # Try to pluck the app name out of the prompt
            import re
            m = re.search(r"app:\s*([\w-]+)", prompt)
            app = m.group(1) if m else "this service"
            text = (
                f"`{app}` participates in the enterprise banking platform; see the "
                f"generated sections below for the contracts it provides and consumes. "
                f"(Mock LLM — swap `SHERLOCK_LLM_PROVIDER` to Gemini or Azure OpenAI for a richer summary.)"
            )
        else:
            text = "(mock LLM response — no provider configured)"
        return LLMResponse(text=text, model=self.model, provider=self.name)
