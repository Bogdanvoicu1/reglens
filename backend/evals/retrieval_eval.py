"""Deterministic retrieval evaluation: recall@K and MRR over the golden dataset.

Metrics are computed at the document level: retrieved chunks are deduplicated
to ordered (corpus, ref) pairs, so retrieving three chunks of Art. 6 counts
once, at the rank of the first.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.retrieval.hybrid import RetrievedChunk, retrieve
from app.services.embeddings import EmbeddingClient
from evals.loader import EvalEntry


def doc_ranking(chunks: list[RetrievedChunk]) -> list[tuple[str, str]]:
    return list(dict.fromkeys((c.corpus_slug, c.ref) for c in chunks))


def question_recall(entry: EvalEntry, ranking: list[tuple[str, str]], k: int) -> float:
    expected = {e.key for e in entry.expected}
    hits = expected & set(ranking[:k])
    if entry.require == "any":
        return 1.0 if hits else 0.0
    return len(hits) / len(expected)


def question_rr(entry: EvalEntry, ranking: list[tuple[str, str]]) -> float:
    expected = {e.key for e in entry.expected}
    for i, key in enumerate(ranking, start=1):
        if key in expected:
            return 1.0 / i
    return 0.0


@dataclass
class RetrievalResult:
    entry_id: str
    category: str
    recall_at_5: float
    recall_at_8: float
    rr: float
    top_refs: list[str]


async def run_retrieval_eval(
    session: AsyncSession, entries: list[EvalEntry]
) -> tuple[list[RetrievalResult], dict]:
    embedder = EmbeddingClient()
    try:
        embeddings = await embedder.embed([e.question for e in entries])
    finally:
        await embedder.aclose()

    results: list[RetrievalResult] = []
    for entry, embedding in zip(entries, embeddings, strict=True):
        chunks = await retrieve(session, entry.question, embedding, top_k=8)
        ranking = doc_ranking(chunks)
        results.append(
            RetrievalResult(
                entry_id=entry.id,
                category=entry.category,
                recall_at_5=question_recall(entry, ranking, 5),
                recall_at_8=question_recall(entry, ranking, 8),
                rr=question_rr(entry, ranking),
                top_refs=[f"{c}:{r}" for c, r in ranking[:5]],
            )
        )

    n = len(results)
    metrics = {
        "n": n,
        "recall_at_5": round(sum(r.recall_at_5 for r in results) / n, 4),
        "recall_at_8": round(sum(r.recall_at_8 for r in results) / n, 4),
        "mrr": round(sum(r.rr for r in results) / n, 4),
        "misses": [r.entry_id for r in results if r.recall_at_8 == 0.0],
    }
    return results, metrics
