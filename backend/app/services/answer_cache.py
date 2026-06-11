"""Answer cache: identical questions against an unchanged corpus skip the LLM.

The key binds the normalized question to the generation model and the exact
corpus versions involved, so re-ingesting a corpus or switching models
invalidates naturally. Only successful grounded answers are cached — never
refusals or errors.
"""

import hashlib
import json
import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Corpus
from app.services.redis import get_redis

log = structlog.get_logger()

_WS = re.compile(r"\s+")


def normalize_question(question: str) -> str:
    return _WS.sub(" ", question.strip().lower())


async def corpus_fingerprint(session: AsyncSession, corpus_slugs: list[str] | None) -> str:
    q = select(Corpus.slug, Corpus.version).order_by(Corpus.slug, Corpus.version)
    if corpus_slugs:
        q = q.where(Corpus.slug.in_(corpus_slugs))
    rows = (await session.execute(q)).all()
    return ";".join(f"{s}@{v}" for s, v in rows)


def cache_key(question: str, fingerprint: str, top_k: int) -> str:
    settings = get_settings()
    raw = f"{settings.generation_model}|{fingerprint}|{top_k}|{normalize_question(question)}"
    return "ans:" + hashlib.sha256(raw.encode()).hexdigest()


async def get_cached_answer(key: str) -> dict | None:
    try:
        payload = await get_redis().get(key)
    except Exception:
        log.warning("answer_cache_unavailable")
        return None
    return json.loads(payload) if payload else None


async def set_cached_answer(key: str, value: dict) -> None:
    try:
        await get_redis().set(key, json.dumps(value), ex=get_settings().answer_cache_ttl_seconds)
    except Exception:
        log.warning("answer_cache_write_failed")
