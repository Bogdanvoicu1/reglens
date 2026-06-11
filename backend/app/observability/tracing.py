"""Optional Langfuse LLM tracing.

Activated only when both REGLENS_LANGFUSE_PUBLIC_KEY and
REGLENS_LANGFUSE_SECRET_KEY are set; otherwise every call here is a no-op.
One trace per chat request: a retrieval span (query → refs/scores) and a
generation observation (model, token usage, cost). The SDK batches and ships
events on a background thread, so tracing never blocks the response stream.
"""

from functools import lru_cache
from typing import Any

import structlog

from app.core.config import get_settings

log = structlog.get_logger()


@lru_cache
def get_langfuse() -> Any | None:
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception:
        log.exception("langfuse_init_failed")
        return None


class ChatTrace:
    """Thin wrapper so the chat route stays readable; safe when tracing is off."""

    def __init__(self, question: str, user_id: str, tenant_id: str) -> None:
        client = get_langfuse()
        self._trace = (
            client.trace(
                name="chat",
                input={"question": question},
                user_id=user_id,
                metadata={"tenant_id": tenant_id},
            )
            if client
            else None
        )

    def retrieval(self, query: str) -> "_Span":
        return _Span(
            self._trace.span(name="retrieval", input={"query": query}) if self._trace else None
        )

    def generation(self, model: str, messages: list[dict]) -> "_Generation":
        return _Generation(
            self._trace.generation(name="generation", model=model, input=messages)
            if self._trace
            else None
        )

    def end(self, output: dict) -> None:
        if self._trace:
            self._trace.update(output=output)


class _Span:
    def __init__(self, span: Any | None) -> None:
        self._span = span

    def end(self, output: Any) -> None:
        if self._span:
            self._span.end(output=output)


class _Generation:
    def __init__(self, gen: Any | None) -> None:
        self._gen = gen

    def end(self, output: str, usage: dict | None) -> None:
        if self._gen:
            usage_payload = None
            if usage:
                usage_payload = {
                    "input": usage.get("prompt_tokens"),
                    "output": usage.get("completion_tokens"),
                    "total": usage.get("total_tokens"),
                    "unit": "TOKENS",
                }
            self._gen.end(
                output=output,
                usage=usage_payload,
                metadata={"cost_usd": usage.get("cost")} if usage else None,
            )
