"""End-to-end generation evaluation through the production pipeline.

Runs retrieve → grounded generation → citation validation for every entry,
then judges valid answers with a stronger model. Refusal-expected entries are
scored deterministically (no judge): correct iff the pipeline refused, either
pre-generation (weak retrieval) or via the model's refusal protocol.
"""

import asyncio
from dataclasses import asdict, dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes.chat import MIN_TOP_SCORE
from app.rag.generation.grounded import build_messages, group_sources, validate_answer
from app.rag.retrieval.hybrid import retrieve
from app.services.embeddings import EmbeddingClient
from app.services.llm import ChatClient
from evals.judge import JudgeClient
from evals.loader import EvalEntry

log = structlog.get_logger()

CONCURRENCY = 4


@dataclass
class GenerationResult:
    entry_id: str
    category: str
    expect_refusal: bool
    status: str  # ok | refused_pre | refusal | citation_error | no_citations | error
    faithfulness: float | None = None
    citation_precision: float | None = None
    answer_relevance: float | None = None
    judge_verdict: str | None = None
    unsupported_claims: list[str] | None = None
    answer_preview: str = ""


async def _eval_one(
    entry: EvalEntry,
    embedding: list[float],
    sessionmaker: async_sessionmaker[AsyncSession],
    llm: ChatClient,
    judge: JudgeClient,
    sem: asyncio.Semaphore,
) -> GenerationResult:
    async with sem:
        try:
            async with sessionmaker() as session:
                sources = await retrieve(session, entry.question, embedding, top_k=8)
            if not sources or sources[0].score < MIN_TOP_SCORE:
                return GenerationResult(
                    entry.id, entry.category, entry.expect_refusal, "refused_pre"
                )

            grouped = group_sources(sources)
            result = await llm.complete(build_messages(entry.question, grouped))
            validation = validate_answer(result.text, len(grouped))
            gen = GenerationResult(
                entry.id,
                entry.category,
                entry.expect_refusal,
                validation.status,
                answer_preview=result.text[:200],
            )
            if validation.status == "ok" and not entry.expect_refusal:
                verdict = await judge.judge(entry.question, result.text, grouped)
                gen.faithfulness = float(verdict["faithfulness"])
                gen.citation_precision = float(verdict["citation_precision"])
                gen.answer_relevance = float(verdict["answer_relevance"])
                gen.judge_verdict = verdict.get("verdict")
                gen.unsupported_claims = verdict.get("unsupported_claims", [])
            return gen
        except Exception as exc:
            log.exception("generation_eval_failed", entry=entry.id)
            return GenerationResult(
                entry.id, entry.category, entry.expect_refusal, "error", answer_preview=str(exc)
            )


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


async def run_generation_eval(
    sessionmaker: async_sessionmaker[AsyncSession],
    entries: list[EvalEntry],
    *,
    judge_model: str | None = None,
    generation_model: str | None = None,
) -> tuple[list[GenerationResult], dict]:
    embedder = EmbeddingClient()
    llm = ChatClient(generation_model)
    judge = JudgeClient(judge_model)
    try:
        embeddings = await embedder.embed([e.question for e in entries])
        sem = asyncio.Semaphore(CONCURRENCY)
        results = await asyncio.gather(
            *(
                _eval_one(entry, emb, sessionmaker, llm, judge, sem)
                for entry, emb in zip(entries, embeddings, strict=True)
            )
        )
    finally:
        await embedder.aclose()
        await llm.aclose()
        await judge.aclose()

    refused = {"refused_pre", "refusal"}
    refusal_entries = [r for r in results if r.expect_refusal]
    answerable = [r for r in results if not r.expect_refusal]
    judged = [r for r in answerable if r.faithfulness is not None]

    from app.core.config import get_settings

    metrics = {
        "n": len(results),
        "generation_model": generation_model or get_settings().generation_model,
        "refusal_accuracy": _mean([1.0 if r.status in refused else 0.0 for r in refusal_entries]),
        "false_refusal_rate": _mean([1.0 if r.status in refused else 0.0 for r in answerable]),
        "faithfulness": _mean([r.faithfulness for r in judged]),
        "citation_precision": _mean([r.citation_precision for r in judged]),
        "answer_relevance": _mean([r.answer_relevance for r in judged]),
        "judge_pass_rate": _mean([1.0 if r.judge_verdict == "pass" else 0.0 for r in judged]),
        "validation_failures": [
            {"id": r.entry_id, "status": r.status}
            for r in answerable
            if r.status not in {"ok"} | refused
        ],
        "incorrect_refusals": [r.entry_id for r in answerable if r.status in refused],
        "missed_refusals": [r.entry_id for r in refusal_entries if r.status not in refused],
    }
    return list(results), metrics


def results_to_dicts(results: list[GenerationResult]) -> list[dict]:
    return [asdict(r) for r in results]
