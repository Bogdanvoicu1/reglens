# RAG System Review — should we change it?

**Date:** 2026-06-14
**Reviewer perspective:** RAG systems engineer; mandate = improve retrieval quality *without over-engineering*.
**Scope:** the `/api/v1/chat` RAG path — ingestion, hybrid retrieval, grounded generation, evals. (The v2 assessment agent was read for context but is out of scope here.)

---

## TL;DR — verdict

**Do not rewrite it, and do not migrate it to LangChain.** The current system is a lean (~700 LOC core), correct, well-instrumented RAG that *already implements the patterns a LangChain build would give you* — hybrid pgvector + FTS with RRF, contextual-header chunking, grouped cited sources, refusal-before-generation, prompt-injection defense, and a CI-gated eval harness. In several places it **exceeds** the textbook (embedding-dimension validation, corpus-version-keyed caching, a two-tier safety gate). Measured retrieval recall@8 is **1.00** and judged faithfulness is **1.00** — there is no quality fire to fight.

A rewrite or a LangChain migration would be **textbook over-engineering**: it trades working, inspectable code for a heavy abstraction/dependency layer and real regression risk, to chase metrics that are already at ceiling.

There is exactly **one genuine functional gap** worth fixing — **multi-turn / follow-up questions are not handled** — plus **two small, optional** tuning wins. Everything else I'd explicitly leave alone.

| Question | Answer |
|---|---|
| Rewrite the RAG core? | **No** |
| Adopt LangChain / LlamaIndex? | **No** — no payoff, adds weight & risk |
| Change anything at all? | **One thing worth doing** (multi-turn), two optional, the rest: don't |

---

## What the system is (snapshot)

`React SPA → FastAPI (SSE) → hybrid retrieval (pgvector HNSW + Postgres FTS/GIN, RRF) → grounded generation with server-side citation validation`. Postgres for all state, Redis for answer/embedding caches + rate limits, OpenRouter for models.

- **Embeddings:** `text-embedding-3-small`, 1536d (`config.py:34-35`) — exactly the recommended default.
- **Generation:** `gpt-4o-mini`, `temperature=0`, `max_tokens=1024` (`config.py:34-40`, `llm.py:38`).
- **Indexes:** HNSW `vector_cosine_ops` + GIN on a persisted `tsvector` (`db/models.py:67-82`, migrations) — correct production pgvector setup.

---

## Scorecard vs. RAG best practice

| Area | Best practice | RegLens | Verdict |
|---|---|---|---|
| Indexing | Out of request path, transactional, versioned | CLI `ingest`; atomic delete+insert per (slug,version) (`pipeline.py:46-80`) | ✅ Exceeds |
| Embedding hygiene | Pin model; match index/query dims | Pinned in config; **validates response dim** (`embeddings.py:45-46`) | ✅ Exceeds |
| Chunking | Context-aware, bounded | Contextual headers per paragraph; sentence-split oversize (`chunker.py`) | ✅ |
| Retrieval | Hybrid > pure vector; tunable `k` | BM25-equivalent FTS + vector, RRF; `top_k` tunable 1–20 (`hybrid.py`, `chat.py:43`) | ✅ |
| Source formatting | Delimited, labeled blocks (not `\n` soup) | `<source id=n>` blocks, grouped per article (`grounded.py:88-96`) | ✅ Exceeds |
| Grounding/refusal | Refuse when unsupported | Pre-LLM score gate **and** model refusal prefix (`chat.py:142`, `grounded.py:80-81`) | ✅ Exceeds |
| Injection defense | Treat retrieved text as data | System rule #4 + post-hoc citation validation (`grounded.py:79,109-131`) | ✅ |
| Evaluation | Golden set + gates in CI | 54-Q set, recall/MRR/faithfulness gates, non-zero exit, CI | ✅ Exceeds |
| Observability | Traces + metrics | structlog, Prometheus RAG series, optional Langfuse | ✅ |
| Cost | Cap output, cache | Answer+embedding caches, output cap, eval-gated model swaps | ✅ |
| **Multi-turn** | **Contextualize follow-ups before retrieval** | **Not implemented** | ❌ **Gap** |

One ❌ on a long list of ✅/Exceeds. That ratio *is* the argument against a rewrite.

---

## Findings (ranked)

### F1 — Multi-turn follow-ups are not handled  ·  **✅ Implemented (2026-06-14)**  ·  impact: high · effort: medium · risk: medium

> **Done.** `app/rag/retrieval/contextualize.py` rewrites a follow-up into a
> standalone question from the recent turns before retrieval; `chat.py` keys the
> answer cache off the rewritten question. First turns add no LLM call; any
> rewrite failure falls back to the original. Covered by unit tests in
> `tests/test_rag.py`.

The product presents as a threaded chat (conversations, history, `conversation_id`), but **every turn is answered as a standalone question**. Retrieval and generation receive only `req.question`:

- `retrieve(session, req.question, …)` — `chat.py:128`
- `build_messages(req.question, grouped)` — `chat.py:163`
- `conversation_id` is used **only** to persist the exchange (`chat.py:61-83`, `233-236`); prior turns are never loaded.

So "Which AI practices are prohibited?" → "**What about for minors?**" retrieves on *"What about for minors?"* alone — wrong or weak context. For a compliance Q&A tool this is the one gap a user will actually hit.

**Fix (the proportionate one):** add a cheap query-contextualization step — when `conversation_id` is present, rewrite the follow-up into a standalone question using the last 1–2 turns, then run the *existing* pipeline unchanged. This is the skill's history-aware-retrieval pattern; it does **not** require LangChain.

**Two implementation notes that matter:**
1. **Cache correctness.** The answer-cache key is `cache_key(req.question, fingerprint, top_k)` (`chat.py:93`) — no conversation context. If follow-ups start depending on history, the key **must** incorporate the contextualized/standalone question, or follow-ups will collide on cached answers. (Cache the *rewritten* question — bonus: cross-conversation reuse.)
2. **Keep it one extra call.** One small rewrite LLM call only when `conversation_id` is set; first turns stay zero-overhead. Resist turning chat into an agent.

**Scope guard:** rewrite-then-retrieve only. No standing context window, no summarization memory, no agentic loop — those would be the over-engineered version of this fix.

### F2 — MRR held down by recitals outranking operative articles  ·  **Recommend: optional**  ·  impact: low-med · effort: low · risk: low

Already documented as a known, deliberately-un-overfit issue. Recall@8 = 1.00 (generation always gets the right article), but MRR = 0.69 because narrative recitals sit semantically closer to questions and rank above the operative article. `rrf_fuse` (`hybrid.py:35-40`) weights all rankings equally with no notion of chunk *kind*.

**Fix:** kind-weighted RRF — a small multiplier favoring operative articles over recitals at fusion. ~10 lines, gated by the existing retrieval eval. Pure UX polish (the top-listed source matches how a lawyer would cite); **do not** do it without watching the eval, and skip it if the source-ordering UX isn't a complaint.

### F3 — "Parallel" retrieval is actually sequential  ·  **Recommend: doc fix, not code**  ·  impact: negligible · effort: low · risk: low

`retrieve()` awaits vector then FTS sequentially (`hybrid.py:102-103`); the README/docstring say "in parallel." True parallelism needs two DB connections (one `AsyncSession` can't multiplex). Chat latency is dominated by LLM generation, so the win is ~one DB round-trip — not worth new connection-management complexity. **Fix the wording, not the code.**

---

## Explicitly do NOT do these (over-engineering guard)

These are the "obvious" moves that would add cost/complexity for no measurable gain here:

- **❌ Migrate to LangChain / LlamaIndex.** Replaces 700 lines you fully control with an abstraction layer + dependency tree, risks regressing proven metrics, buys nothing the system lacks.
- **❌ Add a cross-encoder reranker.** Recall@8 is already 1.0; a reranker only reorders. If ordering bugs you, F2 (kind-weighted RRF) is cheaper and sufficient.
- **❌ Multi-query / query expansion.** Justified only by recall problems. There are none.
- **❌ SemanticChunker / tiktoken token counting.** Current paragraph chunking suits structured legal text; char/4 estimate has a wide margin vs the 8k limit (`chunker.py:14-16`). Swapping adds a dependency for ~nothing.
- **❌ Turn chat into an agent.** Single-pass is faster, cheaper, more predictable, and already accurate. F1 is a *rewrite step*, not an agent.

---

## Recommendation

**Keep the architecture. Change one thing.**

1. **Do F1 (multi-turn)** — the only change that fixes a real user-facing gap; mind the cache-key note.
2. **Optionally F2** if source ordering is a UX concern — eval-gated, ~10 lines.
3. **F3** — fix the docs.
4. **Hold the line** on the do-not-do list.

Net: this is a system to *extend narrowly*, not rebuild. The discipline already in the codebase (evals, gates, pinned models, versioned corpus) is exactly what makes a small, safe F1 change cheap to land and verify — so let the eval harness gate it, and ship nothing that doesn't move a measured number.
