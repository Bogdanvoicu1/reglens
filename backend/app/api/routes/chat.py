import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.config import get_settings
from app.core.security import AuthContext
from app.db.models import Conversation, Message
from app.db.session import get_session
from app.observability.rag_metrics import CACHE_EVENTS, RETRIEVAL_TOP_SCORE, record_chat
from app.observability.tracing import ChatTrace
from app.rag.generation.grounded import build_messages, validate_answer
from app.rag.retrieval.hybrid import retrieve
from app.services.answer_cache import (
    cache_key,
    corpus_fingerprint,
    get_cached_answer,
    set_cached_answer,
)
from app.services.embeddings import EmbeddingClient
from app.services.llm import ChatClient
from app.services.rate_limit import rate_limited_user

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["chat"])

# Below this fused-RRF score the top hit is too weak to ground an answer;
# refuse before spending generation tokens.
MIN_TOP_SCORE = 0.02


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    corpus_slugs: list[str] | None = Field(default=None, max_length=10)
    top_k: int = Field(default=8, ge=1, le=20)
    conversation_id: uuid.UUID | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _persist_exchange(
    session: AsyncSession,
    auth: AuthContext,
    req: ChatRequest,
    answer: str,
    *,
    citations: dict | None,
    usage: dict | None,
    latency_ms: int,
) -> uuid.UUID:
    conversation_id = req.conversation_id
    if conversation_id is None:
        conversation = Conversation(
            tenant_id=auth.tenant_id, user_id=auth.user_id, title=req.question[:300]
        )
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id
    session.add_all(
        [
            Message(conversation_id=conversation_id, role="user", content=req.question),
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                citations=citations,
                usage=usage,
                latency_ms=latency_ms,
            ),
        ]
    )
    await session.commit()
    return conversation_id


async def _chat_stream(
    req: ChatRequest, session: AsyncSession, auth: AuthContext
) -> AsyncIterator[str]:
    start = time.perf_counter()
    trace = ChatTrace(req.question, str(auth.user_id), str(auth.tenant_id))
    try:
        fingerprint = await corpus_fingerprint(session, req.corpus_slugs)
        key = cache_key(req.question, fingerprint, req.top_k)
        if cached := await get_cached_answer(key):
            CACHE_EVENTS.labels("hit").inc()
            latency_ms = round((time.perf_counter() - start) * 1000)
            record_chat("cached", latency_ms / 1000)
            trace.end({"status": "cached"})
            conversation_id = await _persist_exchange(
                session,
                auth,
                req,
                cached["answer"],
                citations=cached["citations"],
                usage=None,
                latency_ms=latency_ms,
            )
            yield _sse("sources", {"sources": cached["sources"]})
            yield _sse("token", {"token": cached["answer"]})
            yield _sse(
                "done",
                {
                    "status": "ok",
                    "cached": True,
                    "cited_sources": cached["citations"]["cited"],
                    "conversation_id": str(conversation_id),
                    "latency_ms": latency_ms,
                },
            )
            return

        CACHE_EVENTS.labels("miss").inc()
        embedder = EmbeddingClient()
        llm = ChatClient()
        try:
            retrieval_span = trace.retrieval(req.question)
            query_embedding = (await embedder.embed([req.question]))[0]
            sources = await retrieve(
                session,
                req.question,
                query_embedding,
                corpus_slugs=req.corpus_slugs,
                top_k=req.top_k,
            )
            retrieval_span.end(
                [{"ref": s.ref, "corpus": s.corpus_slug, "score": s.score} for s in sources]
            )
            if sources:
                RETRIEVAL_TOP_SCORE.observe(sources[0].score)

            if not sources or sources[0].score < MIN_TOP_SCORE:
                record_chat("refused_pre", time.perf_counter() - start)
                trace.end({"status": "refused_pre"})
                yield _sse(
                    "refusal",
                    {"reason": "No sufficiently relevant passages found in the corpus."},
                )
                return

            source_payload = [
                {
                    "id": i,
                    "ref": s.ref,
                    "title": s.document_title,
                    "corpus": s.corpus_slug,
                    "text": s.text,
                }
                for i, s in enumerate(sources, start=1)
            ]
            yield _sse("sources", {"sources": source_payload})

            prompt_messages = build_messages(req.question, sources)
            generation = trace.generation(get_settings().generation_model, prompt_messages)
            result = None
            async for token, result in llm.stream(  # noqa: B007 — result accumulates state
                prompt_messages
            ):
                yield _sse("token", {"token": token})

            full_text = result.text if result else ""
            validation = validate_answer(full_text, len(sources))
            latency_ms = round((time.perf_counter() - start) * 1000)
            usage = result.usage if result else {}
            generation.end(full_text, usage)
            record_chat(validation.status, latency_ms / 1000, usage)
            trace.end({"status": validation.status, "cited": validation.cited_indices})
            log.info(
                "chat_answer",
                status=validation.status,
                cited=validation.cited_indices,
                latency_ms=latency_ms,
                usage=usage,
                tenant_id=str(auth.tenant_id),
            )
            if validation.status == "refusal":
                yield _sse("refusal", {"reason": validation.detail})
                return

            citations = {"cited": validation.cited_indices}
            conversation_id = await _persist_exchange(
                session,
                auth,
                req,
                full_text,
                citations=citations,
                usage=usage,
                latency_ms=latency_ms,
            )
            if validation.status == "ok":
                await set_cached_answer(
                    key,
                    {"answer": full_text, "sources": source_payload, "citations": citations},
                )
            yield _sse(
                "done",
                {
                    "status": validation.status,
                    "cached": False,
                    "cited_sources": validation.cited_indices,
                    "detail": validation.detail,
                    "conversation_id": str(conversation_id),
                    "latency_ms": latency_ms,
                    "usage": usage,
                },
            )
        finally:
            await embedder.aclose()
            await llm.aclose()
    except Exception:
        log.exception("chat_stream_failed")
        record_chat("error", time.perf_counter() - start)
        trace.end({"status": "error"})
        yield _sse("error", {"message": "Internal error while generating the answer."})


@router.post("/chat")
async def chat(
    req: ChatRequest,
    auth: Annotated[AuthContext, Depends(rate_limited_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if req.conversation_id is not None:
        conversation = await session.get(Conversation, req.conversation_id)
        if conversation is None or conversation.tenant_id != auth.tenant_id:
            raise HTTPException(status_code=404, detail="Conversation not found")
    return StreamingResponse(
        _chat_stream(req, session, auth),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
