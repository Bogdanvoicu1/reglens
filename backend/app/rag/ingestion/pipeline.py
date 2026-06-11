"""Ingestion pipeline: fetch → parse → chunk → embed → store.

Re-ingesting a (slug, version) pair replaces the previous corpus atomically:
the delete and inserts happen in one transaction, so readers never see a
half-ingested corpus.
"""

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Corpus, Document
from app.rag.ingestion.chunker import chunk_document
from app.rag.ingestion.fetcher import fetch_corpus_html
from app.rag.ingestion.parser import parse_corpus_html
from app.rag.ingestion.registry import CorpusSpec
from app.services.embeddings import EmbeddingClient

log = structlog.get_logger()


async def ingest_corpus(
    session: AsyncSession,
    spec: CorpusSpec,
    *,
    skip_embed: bool = False,
    force_fetch: bool = False,
) -> dict[str, int]:
    html = fetch_corpus_html(spec, force=force_fetch)
    parsed = parse_corpus_html(html)
    if not parsed:
        raise ValueError(f"Parser produced no documents for {spec.slug}")

    doc_chunks = [(doc, chunk_document(doc, spec.title)) for doc in parsed]
    all_chunks = [c for _, chunks in doc_chunks for c in chunks]
    log.info("parsed_corpus", corpus=spec.slug, documents=len(parsed), chunks=len(all_chunks))

    embeddings: list[list[float]] | None = None
    if not skip_embed:
        client = EmbeddingClient()
        try:
            embeddings = await client.embed([c.text for c in all_chunks])
        finally:
            await client.aclose()

    existing = await session.scalar(
        select(Corpus).where(Corpus.slug == spec.slug, Corpus.version == spec.version)
    )
    if existing:
        await session.execute(delete(Corpus).where(Corpus.id == existing.id))

    corpus = Corpus(
        slug=spec.slug, title=spec.title, version=spec.version, source_url=spec.source_url
    )
    session.add(corpus)
    await session.flush()

    vec_iter = iter(embeddings) if embeddings is not None else None
    for doc, chunks in doc_chunks:
        document = Document(
            corpus_id=corpus.id,
            kind=doc.kind,
            ref=doc.ref,
            title=doc.title,
            full_text=doc.full_text,
        )
        session.add(document)
        await session.flush()
        session.add_all(
            Chunk(
                document_id=document.id,
                ord=i,
                text=chunk.text,
                token_count=chunk.token_count,
                embedding=next(vec_iter) if vec_iter else None,
            )
            for i, chunk in enumerate(chunks)
        )

    await session.commit()
    return {"documents": len(parsed), "chunks": len(all_chunks)}
