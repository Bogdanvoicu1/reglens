from pathlib import Path

import httpx
import structlog

from app.rag.ingestion.registry import CorpusSpec

log = structlog.get_logger()

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"

_HEADERS = {"User-Agent": "Mozilla/5.0 (RegLens ingestion; contact: see repo)"}


def fetch_corpus_html(spec: CorpusSpec, *, force: bool = False) -> str:
    """Download the EUR-Lex HTML for a corpus, caching it on disk.

    The cache keeps ingestion reproducible and avoids hammering EUR-Lex while
    iterating on the parser.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / f"{spec.slug}-{spec.version}.html"
    if cache_path.exists() and not force:
        log.info("fetch_cache_hit", corpus=spec.slug, path=str(cache_path))
        return cache_path.read_text()

    log.info("fetch_download", corpus=spec.slug, url=spec.source_url)
    resp = httpx.get(spec.source_url, headers=_HEADERS, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    html = resp.text
    if 'class="eli-subdivision"' not in html:
        raise ValueError(f"Unexpected EUR-Lex response for {spec.slug}: no ELI subdivisions found")
    cache_path.write_text(html)
    return html
