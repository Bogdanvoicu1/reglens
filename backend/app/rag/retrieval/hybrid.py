"""Hybrid retrieval: pgvector cosine + Postgres full-text, fused with RRF.

Dense vectors catch paraphrases ("can I use face recognition in public?");
full-text catches exact legal vocabulary ("Art 6(1)(f) legitimate interests").
Reciprocal rank fusion combines both without score calibration.
"""

import re
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Corpus, Document
from app.observability.redaction import loggable_question

log = structlog.get_logger()

RRF_K = 60
CANDIDATES_PER_RETRIEVER = 20


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    text: str
    ref: str
    document_title: str
    corpus_slug: str
    score: float


def rrf_fuse(rankings: list[list[uuid.UUID]], k: int = RRF_K) -> dict[uuid.UUID, float]:
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def _base_query(corpus_slugs: list[str] | None) -> Select[tuple[uuid.UUID]]:
    q = (
        select(Chunk.id)
        .join(Document, Chunk.document_id == Document.id)
        .join(Corpus, Document.corpus_id == Corpus.id)
    )
    if corpus_slugs:
        q = q.where(Corpus.slug.in_(corpus_slugs))
    return q


async def _vector_ranking(
    session: AsyncSession, embedding: list[float], corpus_slugs: list[str] | None
) -> list[uuid.UUID]:
    q = (
        _base_query(corpus_slugs)
        .where(Chunk.embedding.is_not(None))
        .order_by(Chunk.embedding.cosine_distance(embedding))
        .limit(CANDIDATES_PER_RETRIEVER)
    )
    return list((await session.scalars(q)).all())


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9-]+")

# Acronyms practitioners type but the regulations only ever spell out. Full-text
# search for the acronym itself ("DPIA") matches nothing, so the term reaches
# only the dense vector — and a vector-only hit can't clear the cross-retriever
# agreement the answer gate requires (MIN_TOP_SCORE). Expanding to the canonical
# phrase lets full-text find the article (e.g. GDPR Art. 35) too.
#
# Only acronyms whose spelled-out form names a specific provision belong here.
# "GDPR" is deliberately excluded: its expansion ("general data protection
# regulation") sits in every GDPR chunk's header, so expanding it would match
# the whole corpus and drown the signal.
_ACRONYM_EXPANSIONS = {
    "dpia": "data protection impact assessment",
    "dpo": "data protection officer",
}


def expand_acronyms(query: str) -> str:
    tokens = dict.fromkeys(m.group(0).lower() for m in _WORD.finditer(query))
    extra = [_ACRONYM_EXPANSIONS[t] for t in tokens if t in _ACRONYM_EXPANSIONS]
    return f"{query} {' '.join(extra)}" if extra else query


def fts_query_text(query: str) -> str:
    """OR the query's words for websearch_to_tsquery.

    AND semantics (the default) makes the whole query fail when any term is
    absent from the legal text (e.g. "GDPR", which the regulation never calls
    itself). OR + ts_rank degrades gracefully: more matched terms rank higher.
    """
    query = expand_acronyms(query)
    return " OR ".join(dict.fromkeys(m.group(0).lower() for m in _WORD.finditer(query)))


async def _fts_ranking(
    session: AsyncSession, query: str, corpus_slugs: list[str] | None
) -> list[uuid.UUID]:
    from sqlalchemy import func

    tsquery = func.websearch_to_tsquery("english", fts_query_text(query))
    q = (
        _base_query(corpus_slugs)
        .where(Chunk.tsv.op("@@")(tsquery))
        .order_by(func.ts_rank(Chunk.tsv, tsquery).desc())
        .limit(CANDIDATES_PER_RETRIEVER)
    )
    return list((await session.scalars(q)).all())


async def retrieve(
    session: AsyncSession,
    query: str,
    query_embedding: list[float],
    *,
    corpus_slugs: list[str] | None = None,
    top_k: int = 8,
) -> list[RetrievedChunk]:
    vector_ids = await _vector_ranking(session, query_embedding, corpus_slugs)
    fts_ids = await _fts_ranking(session, query, corpus_slugs)
    fused = rrf_fuse([vector_ids, fts_ids])
    top_ids = sorted(fused, key=lambda i: fused[i], reverse=True)[:top_k]

    rows = (
        await session.execute(
            select(Chunk, Document.ref, Document.title, Corpus.slug)
            .join(Document, Chunk.document_id == Document.id)
            .join(Corpus, Document.corpus_id == Corpus.id)
            .where(Chunk.id.in_(top_ids))
        )
    ).all()
    by_id = {
        chunk.id: RetrievedChunk(
            chunk_id=chunk.id,
            text=chunk.text,
            ref=ref,
            document_title=title,
            corpus_slug=slug,
            score=fused[chunk.id],
        )
        for chunk, ref, title, slug in rows
    }
    results = [by_id[i] for i in top_ids if i in by_id]
    log.info(
        "retrieval",
        query=loggable_question(query),
        vector_hits=len(vector_ids),
        fts_hits=len(fts_ids),
        returned=len(results),
        top_score=results[0].score if results else 0.0,
    )
    return results
