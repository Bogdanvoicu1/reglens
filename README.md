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

### Authentication

The API verifies Supabase-compatible JWTs — either HS256 with
`REGLENS_SUPABASE_JWT_SECRET` (legacy projects, local dev) or asymmetric keys
via `REGLENS_SUPABASE_JWKS_URL` (new Supabase projects). A user's first
authenticated request just-in-time provisions a personal tenant; an
`app_metadata.tenant_id` claim attaches users to an existing workspace
instead. For local development, mint a token without any Supabase project:

```bash
uv run python scripts/dev_token.py --email you@example.com
curl -N localhost:8000/api/v1/chat \
  -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
  -d '{"question":"Which AI practices are prohibited?"}'
```

### Caching & rate limiting

- Successful grounded answers are cached in Redis, keyed by normalized
  question + generation model + exact corpus versions (re-ingesting or
  switching models invalidates naturally). Repeat questions return in ~1ms.
- Per-tenant sliding-window rate limiting (default 30 req/min) runs as a
  single atomic Redis Lua script; 429 responses carry `Retry-After`. Limits
  survive API restarts because the window lives in Redis.

- API docs: http://localhost:8000/docs
- Metrics: http://localhost:8000/metrics/ · Grafana: http://localhost:3001

## Evaluation

RegLens ships a versioned golden dataset (47 labeled questions over both
regulations, including out-of-corpus and prompt-injection adversarial cases)
and a threshold-gated eval harness that exercises the real production
pipeline:

```bash
cd backend
uv run python -m evals.cli retrieval     # deterministic: recall@K, MRR
uv run python -m evals.cli generation    # full pipeline + LLM-as-judge
```

Measured baseline (dataset v1, `gpt-4o-mini` generation, `gpt-4o` judge):

| Metric | Result | Gate |
|---|---|---|
| Retrieval recall@8 | **1.00** | ≥ 0.85 |
| Retrieval recall@5 | 0.93 | — |
| Retrieval MRR | 0.71 | ≥ 0.60 |
| Faithfulness (judge) | **0.98** | ≥ 0.80 |
| Citation precision (judge) | 0.95 | ≥ 0.80 |
| Answer relevance (judge) | 0.99 | — |
| Refusal accuracy (adversarial) | **1.00** | ≥ 0.80 |
| False refusal rate | 0.00 | ≤ 0.10 |

The CLI exits non-zero on any gate failure, persists runs to the `eval_runs`
table, and writes a full report to `evals/reports/latest.json`. A
`workflow_dispatch` GitHub Action provisions Postgres, ingests the corpus,
and runs the suite in CI.

Known tuning opportunity (documented, intentionally not over-fit): recitals
often outrank operative articles in MRR because their narrative style is
semantically closer to natural questions; kind-weighted RRF would lift MRR
further. Recall@8 = 1.0 means generation always receives the right article.

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
- [x] M2 — Hybrid retrieval (pgvector + FTS + RRF) + grounded generation with citation validation + SSE
- [x] M3 — Supabase-compatible JWT auth, JIT tenancy, Redis sliding-window rate limiting, answer caching, conversation history
- [x] M4 — Evaluation harness: golden dataset, recall@K/MRR, LLM-judge faithfulness, threshold gates, CI workflow
- [ ] M5 — React frontend
- [ ] M6 — Grafana dashboards, hardening
- [ ] M7 — Docs & demo
