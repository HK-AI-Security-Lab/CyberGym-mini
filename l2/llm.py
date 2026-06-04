"""Thin OpenAI-compatible chat wrapper (yunwu.ai).

We deliberately use plain text chat completions (no native function-calling),
because the agent protocol is a text JSON-action loop that is portable across
the Claude / GPT models exposed by the proxy.
"""
import time

from openai import (
    OpenAI, OpenAIError, APIConnectionError, APITimeoutError, RateLimitError,
    InternalServerError,
)
from . import config

_client = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL,
                         timeout=90.0, max_retries=0)
    return _client


def _model_order(model=None):
    ordered = []
    for m in ([model] if model else []) + config.LLM_FALLBACK_MODELS:
        if m and m not in ordered:
            ordered.append(m)
    return ordered or [config.LLM_MODEL]


def chat(messages, model=None, temperature=0.2, max_tokens=2048, attempts=4) -> str:
    last = None
    for i in range(attempts):
        for m in _model_order(model):
            try:
                resp = client().chat.completions.create(
                    model=m,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content or ""
            except (APIConnectionError, APITimeoutError, RateLimitError,
                    InternalServerError, OpenAIError) as e:
                last = e
                continue
        time.sleep(min(2 ** i, 12))
    raise last
