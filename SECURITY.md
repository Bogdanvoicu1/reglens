# Security

This document describes RegLens's threat model, the controls in place, and
what a production deployment must add. It was written against a standard
LLM-application security checklist; items deliberately out of scope are
listed with rationale rather than silently skipped.

## Threat model

| Threat | Vector | Posture |
|---|---|---|
| Prompt injection | User question tries to override instructions, extract the system prompt, or pull the model off-corpus | Mitigated (multiple layers, red-team tested) |
| Injection via corpus | Malicious text in retrieved documents | Low exposure: corpus is fetched only from EUR-Lex by an operator-run CLI; no user uploads exist |
| Credential leakage | Keys in code, git history, or logs | Verified clean (history-wide scan); secrets only via env/CI secrets |
| Cross-tenant data access | One workspace reading another's conversations | Tenant scoping enforced in every query; covered by tests |
| Resource abuse | Flooding, runaway generation cost | Per-tenant sliding-window rate limits; `max_tokens` cap; 64KB body limit; answer + embedding caches |
| XSS via model output | Answer containing markup | Frontend renders text nodes only — no HTML injection path |

## Prompt-injection defenses (defense in depth)

1. **Structural separation** — the system prompt is static; user input only
   ever appears in the user message, after delimited `<source>` blocks.
   Nothing user-controlled is concatenated into instructions.
2. **Sources are data** — the system prompt instructs the model that source
   text is never instructions (relevant if the corpus were ever extended to
   user uploads).
3. **Retrieval gate** — off-corpus questions are refused *before* generation
   based on fused retrieval confidence (no tokens spent).
4. **Refusal protocol** — the model must answer only from sources or emit a
   structured refusal; the API converts it to a `refusal` event.
5. **Server-side output validation** — every `[n]` citation must map to a
   provided source; answers with invented citations are flagged, and only
   validated answers are cached.
6. **Red-team evals in the harness** — adversarial cases (instruction
   override, system-prompt extraction, instruction translation,
   outside-knowledge bait, fictional articles) run through the *production
   pipeline* with a CI-gateable refusal-accuracy threshold. The system prompt
   contains nothing confidential by design — extraction resistance is tested,
   but the prompt is not a secret.

## Secrets & keys

- All secrets via environment (`pydantic-settings`); `.env` is gitignored and
  was never committed (verified across full history).
- CI uses GitHub Actions secrets. Use **separate provider keys per
  environment** so a leaked dev key cannot burn production quota.
- JWTs verified via HS256 secret or JWKS (asymmetric); tokens are never
  logged.

## Privacy in logs & traces

User questions can be confidential. By default
(`REGLENS_LOG_QUESTION_TEXT=false`) logs and Langfuse traces carry a short
SHA-256 hash of the question instead of plaintext — enough to correlate
repeats, nothing more. Enable plaintext only in development.

## Production deployment checklist

- [ ] TLS at the reverse proxy; enable HSTS (the API serves HTTP behind it)
- [ ] Deploy with the base compose file only (`docker compose -f
  docker-compose.yml up -d`) — the dev override publishes Postgres/Redis to
  the host and must not be used in production
- [ ] Change the dev defaults: Postgres password, Grafana admin password
- [ ] Restrict `/metrics/` (internal network or auth) — it reveals usage and
  spend
- [ ] Set per-environment LLM keys; review unused keys quarterly
- [ ] Add per-IP rate limiting at the edge (nginx `limit_req`) in front of the
  per-tenant application limits
- [ ] Set real CORS origins via `REGLENS_CORS_ORIGINS`

## Out of scope (deliberate)

- **PII detection on outputs** — the corpus is public legislation; outputs
  quote it. A deployment over private documents should add a PII scrubber.
- **Moderation API on outputs** — grounded-only generation over a legal
  corpus constrains the output space; a hook can be added where answers are
  validated.
- **File-upload validation** — no upload surface exists.

## Reporting

This is a portfolio project; please open a GitHub issue for any finding.
