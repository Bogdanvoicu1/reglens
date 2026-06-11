# RegLens — Design Document

## 1. Problem

Companies subject to the EU AI Act and GDPR need fast, trustworthy answers to
compliance questions ("Is my chatbot a high-risk AI system?", "What is the
lawful basis for processing employee biometrics?"). Generic LLM chat is
unacceptable here: answers must be **grounded in the actual legal text, cited
to article/recital level, and refused when the corpus does not support an
answer**. RegLens is a multi-tenant RAG platform that does exactly this, with
a production-grade evaluation, observability, and security story.

## 2. Target users & use cases

| User | Use case |
|---|---|
| Compliance officer / DPO | Ask grounded questions, get cited answers, export them |
| Product/eng teams | Quick checks during feature design ("does this need a DPIA?") |
| Consultancies (tenants) | Serve multiple clients from isolated workspaces |

Non-goals: legal advice (every answer carries a disclaimer), corpora beyond
the curated EU AI Act + GDPR set (v1), fine-tuning.

## 3. System architecture

```
┌────────────┐   HTTPS    ┌─────────────────────────────────────────┐
│ React SPA  │──────────▶│ FastAPI                                  │
│ (Vite, TS) │  SSE/JSON  │  /auth (Supabase JWT verify)            │
└────────────┘            │  /chat ──▶ RAG pipeline                  │
                          │  /documents, /evals, /admin              │
                          └──┬──────────┬──────────┬────────────────┘
                             │          │          │
                      ┌──────▼───┐ ┌────▼────┐ ┌───▼──────────┐
                      │ Postgres │ │  Redis  │ │ LLM providers│
                      │ +pgvector│ │ cache + │ │ (OpenAI /    │
                      │ (Alembic)│ │ ratelim │ │  Anthropic)  │
                      └──────────┘ └─────────┘ └──────────────┘
   Observability: structlog JSON logs → stdout; Prometheus /metrics →
   Grafana dashboards; per-request trace IDs; LLM call tracing (Langfuse opt-in).
```

### RAG pipeline (the core)

1. **Ingestion (offline CLI)**: fetch official EUR-Lex HTML for the AI Act
   (Reg. 2024/1689) and GDPR (Reg. 2016/679) → parse into a structured tree
   (chapter → article → paragraph; recitals separately) → **hierarchy-aware
   chunking** (paragraph-level chunks carrying article/chapter metadata) →
   embed (OpenAI `text-embedding-3-small`) → store in pgvector.
2. **Retrieval**: hybrid search — pgvector cosine + Postgres full-text (BM25
   analogue via `ts_rank`) — fused with reciprocal rank fusion; optional
   cross-encoder rerank.
3. **Generation**: query → retrieval → grounded prompt with numbered source
   blocks → LLM answer constrained to cite `[n]` markers → post-validation
   that every citation maps to a retrieved chunk. If retrieval confidence is
   below threshold or the model signals insufficient grounding → structured
   refusal.
4. **Streaming**: SSE token stream to the SPA; citations resolved client-side
   to article anchors.

### Key decisions & rationale

| Decision | Rationale |
|---|---|
| Postgres + pgvector (no separate vector DB) | One database, real migrations, transactional metadata + vectors; fewer moving parts |
| Supabase Auth (JWT verified locally via JWKS) | Managed auth without vendor lock-in inside the API; tenant id carried in JWT claims |
| Redis for cache + rate limiting | Answer cache (query-hash, per-corpus-version), embedding cache, sliding-window per-tenant rate limits |
| SSE over WebSockets | Unidirectional token streaming; simpler infra, plays well with proxies |
| Eval harness in-repo, CI-gated | Retrieval metrics (recall@K, MRR) are cheap/deterministic → run on every PR; LLM-judge faithfulness evals run on a labeled golden dataset, threshold-gated |
| structlog + Prometheus + Grafana | Self-owned observability, demonstrable in docker-compose, no SaaS dependency |

## 4. Tools, frameworks, models

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2/pydantic-settings, asyncpg, redis-py, httpx
- **Frontend**: React 18 + TypeScript + Vite, TanStack Query, Tailwind
- **Models**: `text-embedding-3-small` (embeddings), `gpt-4o-mini` default generation (configurable; Anthropic supported), LLM-judge evals on `gpt-4o`
- **Infra**: Docker multi-stage builds, docker-compose (api, frontend, postgres+pgvector, redis, prometheus, grafana), GitHub Actions CI (lint, type-check, tests, retrieval evals)
