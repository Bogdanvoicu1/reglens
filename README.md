# RegLens

**Grounded compliance Q&A over the EU AI Act and GDPR** — a production-grade,
multi-tenant RAG platform. Every answer is cited to the article/recital level;
questions the corpus cannot support are refused, not hallucinated.

> ⚠️ RegLens provides information, not legal advice.

## Why this exists

Generic LLM chat is unusable for compliance work: answers must be grounded in
the actual legal text, verifiable, and auditable. RegLens demonstrates how to
build that properly — hybrid retrieval, citation validation, CI-gated
evaluation, multi-tenant auth, rate limiting, caching, and self-hosted
observability — in one inspectable codebase.

## Architecture

React SPA → FastAPI → hybrid retrieval (pgvector + Postgres FTS, reciprocal
rank fusion) → grounded generation with citation post-validation → SSE
streaming. Postgres (Alembic migrations) for all state, Redis for caching and
per-tenant rate limits, Supabase for auth, Prometheus + Grafana for
observability. See [docs/DESIGN.md](docs/DESIGN.md) and
[docs/PLAN.md](docs/PLAN.md).

## Quick start

```bash
docker compose up -d            # postgres+pgvector, redis, api, prometheus, grafana
cd backend
cp .env.example .env            # add your OpenRouter (or OpenAI-compatible) API key
uv sync
uv run alembic upgrade head     # apply migrations
uv run python -m app.cli ingest ai-act gdpr   # fetch, parse, chunk, embed, store
uv run uvicorn app.main:app --reload
```

The ingestion CLI downloads the official EUR-Lex HTML (cached under
`backend/data/raw/`), parses it into articles/recitals, produces
hierarchy-aware chunks with contextual headers, embeds them via the
configured provider, and stores everything transactionally. Use
`--skip-embed` to inspect parsing without an API key.

- API docs: http://localhost:8000/docs
- Metrics: http://localhost:8000/metrics/ · Grafana: http://localhost:3001

## Development

```bash
cd backend
uv run pytest          # tests
uv run ruff check .    # lint
uv run mypy app        # types
```

## Status

- [x] M0 — Foundation: API skeleton, Alembic, Docker, observability middleware, CI
- [x] M1 — Corpus ingestion (EUR-Lex → hierarchy-aware chunks → embeddings, OpenRouter-compatible)
- [ ] M2 — Hybrid retrieval + grounded generation + SSE
- [ ] M3 — Supabase auth, tenancy, rate limiting, caching
- [ ] M4 — Evaluation harness (recall@K / MRR in CI, LLM-judge faithfulness)
- [ ] M5 — React frontend
- [ ] M6 — Grafana dashboards, hardening
- [ ] M7 — Docs & demo
