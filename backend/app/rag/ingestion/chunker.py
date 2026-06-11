"""Hierarchy-aware chunking.

One chunk per legal paragraph, prefixed with a context header (act + article
ref + article title) so embeddings carry document-level context — the
"contextual retrieval" pattern. Oversized paragraphs are split on sentence
boundaries with the header repeated.
"""

import re
from dataclasses import dataclass

from app.rag.ingestion.parser import ParsedDocument

# Rough token estimate (chars/4) keeps the pipeline dependency-light; chunk
# budgets have wide safety margins against embedding model limits (8k tokens).
MAX_CHUNK_TOKENS = 480


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class ChunkData:
    ref: str
    text: str
    token_count: int


_SENTENCE_SPLIT = re.compile(r"(?<=[.;])\s+")


def _split_long(text: str, budget_chars: int) -> list[str]:
    sentences = _SENTENCE_SPLIT.split(text)
    parts: list[str] = []
    current = ""
    for s in sentences:
        if current and len(current) + len(s) + 1 > budget_chars:
            parts.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        parts.append(current)
    return parts


def chunk_document(doc: ParsedDocument, corpus_title: str) -> list[ChunkData]:
    header = f"[{corpus_title} — {doc.ref}" + (f": {doc.title}]" if doc.title else "]")
    budget_chars = (MAX_CHUNK_TOKENS * 4) - len(header)

    chunks: list[ChunkData] = []
    for para in doc.paragraphs:
        pieces = (
            [para.text] if len(para.text) <= budget_chars else _split_long(para.text, budget_chars)
        )
        for piece in pieces:
            text = f"{header}\n{piece}"
            chunks.append(ChunkData(ref=para.ref, text=text, token_count=estimate_tokens(text)))
    return chunks
