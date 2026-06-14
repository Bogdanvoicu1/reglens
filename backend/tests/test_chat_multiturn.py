"""End-to-end multi-turn chat: a follow-up is contextualized against the prior
turns before retrieval. Exercises the real /api/v1/chat path against live
Postgres + Redis (auth, conversation persistence, history loading, cache key);
only retrieval and the LLM/embedding I/O are stubbed.
"""

import re
import uuid

from app.rag.retrieval.hybrid import RetrievedChunk
from app.services.llm import StreamResult
from tests.conftest import mint_token


def _chunk(ref: str, text: str, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        text=text,
        ref=ref,
        document_title="Prohibited AI practices",
        corpus_slug="ai-act",
        score=score,
    )


def _conversation_id(sse_body: str) -> str:
    m = re.search(r'"conversation_id":\s*"([0-9a-f-]+)"', sse_body)
    assert m, f"no conversation_id in response: {sse_body[:500]}"
    return m.group(1)


class TestMultiTurnContextualization:
    async def test_followup_is_rewritten_from_history_before_retrieval(
        self, client, db_available, redis_available, monkeypatch
    ):
        # Unique strings so the answer cache (keyed by question) always misses,
        # keeping the test idempotent across runs.
        tag = uuid.uuid4().hex[:8]
        q1 = f"Which AI practices are prohibited? [{tag}]"
        q2 = "what about for minors?"
        rewritten = f"Which prohibited AI practices apply to minors? [{tag}]"

        retrieve_queries: list[str] = []
        contextualize_msgs: list[list[dict]] = []

        async def fake_retrieve(session, query, query_embedding, *, corpus_slugs=None, top_k=8):
            retrieve_queries.append(query)
            return [
                _chunk("Art. 5", "Prohibited practices include manipulative AI."),
                _chunk(
                    "Art. 5(1)", "Practices exploiting vulnerabilities of minors are prohibited."
                ),
            ]

        async def fake_embed(embedder, question):
            return [0.0] * 1536

        async def fake_complete(self, messages, *, temperature=0.0):
            contextualize_msgs.append(messages)  # the rewriter.complete call
            return StreamResult(text=rewritten)

        async def fake_stream(self, messages, *, temperature=0.0):
            answer = "Prohibited practices are listed [1]."
            yield (
                answer,
                StreamResult(
                    text=answer,
                    usage={"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48},
                ),
            )

        monkeypatch.setattr("app.api.routes.chat.retrieve", fake_retrieve)
        monkeypatch.setattr("app.api.routes.chat.embed_query_cached", fake_embed)
        monkeypatch.setattr("app.services.llm.ChatClient.complete", fake_complete)
        monkeypatch.setattr("app.services.llm.ChatClient.stream", fake_stream)

        headers = {"Authorization": f"Bearer {mint_token(f'mt-{tag}@reglens.local')}"}

        # Turn 1 — no history: retrieval runs on the original question, no rewrite.
        r1 = await client.post("/api/v1/chat", json={"question": q1}, headers=headers)
        assert r1.status_code == 200
        conversation_id = _conversation_id(r1.text)
        assert retrieve_queries == [q1]
        assert contextualize_msgs == []  # first turn never contextualizes

        # Turn 2 — follow-up with history: the bare pronoun question is rewritten
        # into a standalone question, and retrieval runs on THAT.
        r2 = await client.post(
            "/api/v1/chat",
            json={"question": q2, "conversation_id": conversation_id},
            headers=headers,
        )
        assert r2.status_code == 200

        # Contextualization fired exactly once and saw the prior turn's history.
        assert len(contextualize_msgs) == 1
        ctx_user = contextualize_msgs[0][1]["content"]
        assert q1 in ctx_user and q2 in ctx_user

        # The decisive assertion: turn-2 retrieval used the rewritten standalone
        # question, not the bare follow-up.
        assert retrieve_queries == [q1, rewritten]
