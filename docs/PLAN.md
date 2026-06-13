# RegLens — Delivery Plan

## Milestones

- **M0 — Foundation**: repo scaffold, FastAPI skeleton, config, structured
  logging, Postgres + Redis via docker-compose, Alembic baseline migration,
  health/readiness endpoints, CI, tests green.
- **M1 — Ingestion & corpus**: EUR-Lex fetcher + parser, hierarchy-aware
  chunker, embedding pipeline, `reglens ingest` CLI, corpus versioning tables.
- **M2 — Retrieval & RAG API**: hybrid retrieval (vector + FTS + RRF),
  `/chat` endpoint with SSE streaming, citation post-validation, refusal path.
- **M3 — Auth, tenancy, limits**: Supabase JWT verification, tenant model,
  per-tenant rate limiting (Redis sliding window), Redis answer cache.
- **M4 — Evaluation**: golden dataset (~50 labeled Q/A with expected source
  articles), retrieval evals (recall@K, MRR) in CI, LLM-judge faithfulness &
  answer-relevance evals with threshold gates, eval results persisted.
- **M5 — Frontend**: React SPA — auth, chat with streaming + inline
  citations, source viewer, history.
- **M6 — Observability & hardening**: Prometheus metrics (latency, token
  cost, cache hit rate, retrieval scores), Grafana dashboards, error
  taxonomy, load-test sanity, security pass (headers, input limits).
- **M7 — Docs & polish**: README with architecture diagram, demo GIF, setup
  in one command, eval report in README.

## Repository layout

```
reglens/
├── backend/
│   ├── app/
│   │   ├── main.py               # app factory, middleware wiring
│   │   ├── core/                 # config, logging, security (JWT), errors
│   │   ├── api/routes/           # health, chat, documents, evals
│   │   ├── db/                   # engine/session, models, repositories
│   │   ├── rag/                  # ingestion/, retrieval/, generation/
│   │   ├── services/             # cache, rate_limit, llm client
│   │   └── observability/        # metrics, tracing middleware
│   ├── alembic/                  # migrations
│   ├── evals/                    # golden dataset + harness
│   ├── tests/                    # unit + integration (testcontainers-style)
│   └── pyproject.toml
├── frontend/                     # Vite + React + TS
├── infra/                        # prometheus.yml, grafana provisioning
├── docs/                         # DESIGN.md, PLAN.md, API.md
├── docker-compose.yml
└── .github/workflows/ci.yml
```

## Database schema (core tables)

- `tenants(id, name, plan, created_at)`
- `users(id, tenant_id FK, email, role)` — mirrors Supabase identities
- `corpora(id, slug, title, version, source_url, ingested_at)`
- `documents(id, corpus_id FK, kind[article|recital|annex], ref "Art. 6(2)", title, full_text)`
- `chunks(id, document_id FK, ord, text, token_count, embedding vector(1536), tsv tsvector)` — HNSW index on embedding, GIN on tsv
- `conversations(id, tenant_id, user_id, title, created_at)`
- `messages(id, conversation_id FK, role, content, citations jsonb, usage jsonb, latency_ms)`
- `eval_runs(id, git_sha, dataset_version, metrics jsonb, created_at)`

## API surface (v1)

- `GET /healthz`, `GET /readyz`, `GET /metrics`
- `POST /api/v1/chat` → SSE stream (`token`, `citations`, `done`, `refusal` events)
- `GET /api/v1/conversations`, `GET /api/v1/conversations/{id}`
- `GET /api/v1/corpora`, `GET /api/v1/documents/{id}`
- `POST /api/v1/evals/run` (admin), `GET /api/v1/evals/runs`

Auth: `Authorization: Bearer <supabase JWT>`; tenant resolved from claims.
Errors: RFC 7807 problem+json. Rate limits: 429 + `Retry-After`.

## Evaluation strategy

1. **Retrieval (deterministic, every PR)**: golden dataset maps questions →
   expected article refs; assert recall@5 ≥ 0.85, MRR ≥ 0.7.
2. **Generation (LLM-judge, on-demand + nightly)**: faithfulness (claims
   supported by cited chunks), citation precision, refusal correctness on
   adversarial/out-of-corpus questions. Thresholds gate merges to main.
3. **Online**: per-request retrieval scores, token usage, latency exported as
   metrics; cache hit-rate tracked.

## Security / scalability / performance notes

- JWT verified via Supabase JWKS, cached; no service keys in the API path.
- Tenant id scoping enforced in repository layer (every query filtered).
- Input limits (question length, conversation size); prompt-injection
  hardening: retrieved text wrapped in delimited source blocks, system prompt
  forbids instruction-following from sources.
- Horizontal scaling: stateless API, Redis-backed shared state; pgvector HNSW
  for sub-100ms retrieval at this corpus size.
- Caching: normalized-query answer cache keyed by (corpus_version, query
  hash); embedding cache to avoid re-embedding repeated queries.

## Roadmap — v2 (post-M7)

The next flagship capability is the **Compliance Assessment Agent**: a typed,
staged agent that turns a user's system description into a grounded readiness
report (classification, obligations, gap analysis, remediation roadmap) with
per-rule evals and hard safety gates. Full design and milestone plan (A0–A5):
[ASSESSMENT_AGENT.md](ASSESSMENT_AGENT.md).

Status: **A0 — Foundations done** (annex parsing + re-ingest, golden dataset
v3 with annex gates, rulebook v1 with validated schema, 25-scenario
assessment dataset with full per-rule coverage, assessment tables migration).
**A1 — Engine core done** (profile extraction + wave/group-batched rulebook
classification, persistence-first SSE API, CLI runner with scenario diff;
live-verified 57/57 expected verdicts across 4 scenarios incl. blocker
detection, ≈$0.01 per assessment).
**A2 — Full pipeline done** (deterministic obligation mapping, gap analysis,
remediation roadmap with guaranteed blocker coverage, typed report +
markdown export, one-round clarification, deletion, daily assessment rate
limit; report renders end-to-end with a correct priority taxonomy).
**A3 — Frontend done** (Ask/Assess nav, intake form, live SSE stage
timeline, clarification panel, full report view with gap badges + citations
+ remediation roadmap + authenticated markdown download; Playwright-verified
end-to-end).
**A4 — Evals & hardening done** (real-engine scenario suite over 28 scenarios
incl. injection red-team; two-tier safety gate — false-clear rate = 0 hard
gate plus verdict-accuracy / blocker-recall / injection-resistance quality
gates; judge-tier model for the prohibited-practice batch; per-assessment
cost + Grafana panels; wired into the Evals CI workflow).
v2 assessment agent complete (A0–A4); A5 is backlog. Next: M7 — docs &
deploy polish.
