# `app/services` — shared infrastructure

Provider-agnostic clients and Redis-backed state used by the RAG pipeline and
the assessment engine. This is where most of the cost-engineering and
multi-tenant safety levers live.

| File | Role |
|---|---|
| `llm.py` | Streaming client for any OpenAI-compatible `/chat/completions` endpoint (defaults target OpenRouter). `stream()` yields tokens; `complete()` returns the full text + usage (incl. provider-reported `cost`). Output is capped at `generation_max_tokens`. |
| `embeddings.py` | Embedding client (batched: 64 inputs/call during ingestion). |
| `redis.py` | Shared async Redis connection. |
| `answer_cache.py` | Caches grounded answers keyed by normalized question + model + **exact corpus versions** (`corpus_fingerprint`), so re-ingesting or switching models invalidates naturally. Also exposes the fingerprint used by assessments for reproducibility. |
| `embedding_cache.py` | Caches query embeddings (7-day TTL) so repeat questions skip the embedding call even on answer-cache misses. |
| `rate_limit.py` | Per-tenant sliding-window rate limiting via a single atomic Redis Lua script; 429s carry `Retry-After`. Separate namespaces for chat (default 30/min) and assessments (default 5/day, since a run is many LLM calls). |

## Design notes

- **Stateless API, shared state in Redis** — caches and rate-limit windows live
  in Redis, so the API scales horizontally and limits survive restarts.
- **Tenant scoping** is enforced in the repository layer (every query filtered
  by `tenant_id`); these services add the per-tenant rate limits on top.
- **Cost levers** (caching, embedding cache, output capping, batching) are
  measured in the repo README's "Cost engineering" table.
