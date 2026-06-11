"""Embedding client for any OpenAI-compatible /embeddings endpoint (OpenRouter by default)."""

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings

log = structlog.get_logger()

BATCH_SIZE = 64


class EmbeddingError(RuntimeError):
    pass


class EmbeddingClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.llm_api_key:
            raise EmbeddingError("REGLENS_LLM_API_KEY is not set")
        self._model = settings.embedding_model
        self._dim = settings.embedding_dim
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=60,
        )

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post("/embeddings", json={"model": self._model, "input": texts})
        if resp.status_code == 400:
            # Bad requests won't succeed on retry — fail fast with the body.
            raise EmbeddingError(f"Embedding request rejected: {resp.text[:500]}")
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        vectors = [d["embedding"] for d in data]
        if len(vectors) != len(texts) or any(len(v) != self._dim for v in vectors):
            raise EmbeddingError("Embedding response shape mismatch")
        return vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            vectors.extend(await self._embed_batch(batch))
            log.info("embedded_batch", done=len(vectors), total=len(texts))
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()
