"""Streaming chat client for any OpenAI-compatible /chat/completions endpoint."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings


class LLMError(RuntimeError):
    pass


@dataclass
class StreamResult:
    """Filled in as the stream is consumed; complete after iteration ends."""

    text: str = ""
    usage: dict = field(default_factory=dict)


# Messages in, StreamResult out — ChatClient.complete's shape, injectable in
# tests and reused by RAG/assessment stages that call the LLM.
LLMComplete = Callable[[list[dict[str, str]]], Awaitable[StreamResult]]


class ChatClient:
    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        if not settings.llm_api_key:
            raise LLMError("REGLENS_LLM_API_KEY is not set")
        self._model = model or settings.generation_model
        self._max_tokens = settings.generation_max_tokens
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=httpx.Timeout(120, connect=10),
        )

    async def stream(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0
    ) -> AsyncIterator[tuple[str, StreamResult]]:
        """Yield (token, result) pairs; `result` accumulates the full text and usage."""
        result = StreamResult()
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:500]
                raise LLMError(f"LLM request failed ({resp.status_code}): {body}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line.removeprefix("data: ").strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("usage"):
                    result.usage = event["usage"]
                choices = event.get("choices") or []
                if choices:
                    token = choices[0].get("delta", {}).get("content") or ""
                    if token:
                        result.text += token
                        yield token, result

    async def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0
    ) -> StreamResult:
        """Consume the stream and return the final result (for evals and batch use)."""
        result = StreamResult()
        async for _, result in self.stream(messages, temperature=temperature):  # noqa: B007
            pass
        return result

    async def aclose(self) -> None:
        await self._client.aclose()
