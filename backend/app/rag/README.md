# `app/rag` — Retrieval-Augmented Generation pipeline

The core RAG path behind `/api/v1/chat`: ingest the regulations once, then for
each question **retrieve → ground → generate → validate citations → stream**.
Everything an answer asserts is traceable to a specific article or recital, and
weakly-supported questions are refused rather than improvised.

## `ingestion/` — corpus → embedded chunks

Run via `python -m app.cli ingest ai-act gdpr`. One transactional pass:

| File | Role |
|---|---|
| `registry.py` | Declares the corpora (slug, title, EUR-Lex source URL) |
| `fetcher.py` | Downloads the official EUR-Lex HTML, cached under `data/raw/` |
| `parser.py` | Parses HTML into articles, recitals, and all 13 annexes (hierarchy-aware) |
| `chunker.py` | Hierarchy-aware chunking with contextual headers; bounded token sizes |
| `pipeline.py` | Orchestrates fetch → parse → chunk → embed → store, with corpus versioning |

Annex parsing matters: high-risk classification in the assessment agent hinges
on Annex III (use-case list) and Annex I (harmonisation legislation).

## `retrieval/` — hybrid search

`hybrid.py` runs **vector** (pgvector, HNSW) and **full-text** (Postgres FTS,
GIN) search and fuses them with **reciprocal rank fusion (RRF)**.
Returns scored sources; a weak top score short-circuits to a refusal before any
LLM call (off-corpus questions cost $0 in generation).

For multi-turn chat, `contextualize.py` first rewrites a follow-up ("what about
minors?") into a standalone question from the recent turns, so retrieval and the
answer cache key off intent rather than pronouns. First turns skip it (no extra
LLM call); any rewrite failure falls back to the original question, so it can
never retrieve worse than the single-turn baseline.

## `generation/` — grounded answers with validated citations

`grounded.py` builds the prompt (retrieved chunks grouped per article, long
headers replaced by short labels like `GDPR — Art. 6` to save tokens), wraps
sources in delimited blocks the model must treat as **data, not instructions**
(prompt-injection defense), and **post-validates citations** server-side: an
answer may only cite source labels it was actually given, or it is rejected.

## How it fits

`app/services/` provides the LLM client, embeddings, Redis answer/embedding
caches, and rate limiting that this pipeline calls. `evals/` exercises this
exact production path (retrieval recall@K / MRR; LLM-judge faithfulness and
citation precision; refusal correctness) with CI threshold gates — see
[`evals/README.md`](../../evals/README.md).
