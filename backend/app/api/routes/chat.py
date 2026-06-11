import json
import time
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.db.session import get_session
from app.rag.generation.grounded import build_messages, validate_answer
from app.rag.retrieval.hybrid import retrieve
from app.services.embeddings import EmbeddingClient
from app.services.llm import ChatClient

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["chat"])

# Below this fused-RRF score the top hit is too weak to ground an answer;
# refuse before spending generation tokens.
MIN_TOP_SCORE = 0.02


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    corpus_slugs: list[str] | None = Field(default=None, max_length=10)
    top_k: int = Field(default=8, ge=1, le=20)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _chat_stream(req: ChatRequest, session: AsyncSession) -> AsyncIterator[str]:
    start = time.perf_counter()
    embedder = EmbeddingClient()
    llm = ChatClient()
    try:
        query_embedding = (await embedder.embed([req.question]))[0]
        sources = await retrieve(
            session,
            req.question,
            query_embedding,
            corpus_slugs=req.corpus_slugs,
            top_k=req.top_k,
        )

        if not sources or sources[0].score < MIN_TOP_SCORE:
            yield _sse(
                "refusal",
                {"reason": "No sufficiently relevant passages found in the corpus."},
            )
            return

        yield _sse(
            "sources",
            {
                "sources": [
                    {
                        "id": i,
                        "ref": s.ref,
                        "title": s.document_title,
                        "corpus": s.corpus_slug,
                        "text": s.text,
                    }
                    for i, s in enumerate(sources, start=1)
                ]
            },
        )

        result = None
        async for token, result in llm.stream(  # noqa: B007 — result accumulates state
            build_messages(req.question, sources)
        ):
            yield _sse("token", {"token": token})

        full_text = result.text if result else ""
        validation = validate_answer(full_text, len(sources))
        latency_ms = round((time.perf_counter() - start) * 1000)
        log.info(
            "chat_answer",
            status=validation.status,
            cited=validation.cited_indices,
            latency_ms=latency_ms,
            usage=result.usage if result else {},
        )
        if validation.status == "refusal":
            yield _sse("refusal", {"reason": validation.detail})
        else:
            yield _sse(
                "done",
                {
                    "status": validation.status,
                    "cited_sources": validation.cited_indices,
                    "detail": validation.detail,
                    "latency_ms": latency_ms,
                    "usage": result.usage if result else {},
                },
            )
    except Exception:
        log.exception("chat_stream_failed")
        yield _sse("error", {"message": "Internal error while generating the answer."})
    finally:
        await embedder.aclose()
        await llm.aclose()


@router.post("/chat")
async def chat(req: ChatRequest, session: Annotated[AsyncSession, Depends(get_session)]):
    return StreamingResponse(
        _chat_stream(req, session),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
