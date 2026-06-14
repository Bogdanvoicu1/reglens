"""Redis cache for query embeddings.

A repeated question whose answer-cache entry missed (different top_k, evicted,
new corpus version) still skips the embedding API call: same text + same
embedding model ⇒ same vector. Keyed on the normalized question and model,
7-day TTL. Redis being down degrades to a normal embed call.
"""

import hashlib
import json

import structlog
from prometheus_client import Counter

from app.core.config import get_settings
from app.services.answer_cache import normalize_question
from app.services.embeddings import EmbeddingClient
from app.services.redis import get_redis

log = structlog.get_logger()

TTL_SECONDS = 7 * 86400

EMBEDDING_CACHE_EVENTS = Counter(
    "reglens_embedding_cache_events_total", "Query-embedding cache lookups", ["result"]
)


def _key(question: str) -> str:
    digest = hashlib.sha256(normalize_question(question).encode()).hexdigest()
    return f"emb:{get_settings().embedding_model}:{digest}"


async def embed_query_cached(embedder: EmbeddingClient, question: str) -> list[float]:
    key = _key(question)
    try:
        payload = await get_redis().get(key)
    except Exception:
        log.warning("embedding_cache_unavailable")
        payload = None
    if payload:
        EMBEDDING_CACHE_EVENTS.labels("hit").inc()
        cached: list[float] = json.loads(payload)
        return cached

    EMBEDDING_CACHE_EVENTS.labels("miss").inc()
    vector = (await embedder.embed([question]))[0]
    try:
        await get_redis().set(key, json.dumps(vector, separators=(",", ":")), ex=TTL_SECONDS)
    except Exception:
        log.warning("embedding_cache_write_failed")
    return vector
