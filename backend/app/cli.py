"""RegLens ingestion CLI.

Usage:
    python -m app.cli ingest ai-act gdpr
    python -m app.cli ingest ai-act --skip-embed --force-fetch
"""

import argparse
import asyncio
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session
from app.rag.ingestion.pipeline import ingest_corpus
from app.rag.ingestion.registry import CORPORA


async def _run_ingest(slugs: list[str], skip_embed: bool, force_fetch: bool) -> None:
    async for session in get_session():
        for slug in slugs:
            stats = await ingest_corpus(
                session, CORPORA[slug], skip_embed=skip_embed, force_fetch=force_fetch
            )
            print(f"{slug}: {stats['documents']} documents, {stats['chunks']} chunks")


def main() -> None:
    configure_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="reglens")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest one or more corpora")
    ingest.add_argument("corpora", nargs="+", choices=sorted(CORPORA))
    ingest.add_argument(
        "--skip-embed", action="store_true", help="Parse and store without embeddings"
    )
    ingest.add_argument("--force-fetch", action="store_true", help="Bypass the on-disk HTML cache")

    args = parser.parse_args()
    if args.command == "ingest":
        asyncio.run(_run_ingest(args.corpora, args.skip_embed, args.force_fetch))
    else:  # pragma: no cover
        sys.exit(1)


if __name__ == "__main__":
    main()
