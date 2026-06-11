from pathlib import Path

import httpx
import pytest

from app.rag.ingestion.chunker import MAX_CHUNK_TOKENS, chunk_document
from app.rag.ingestion.parser import ParsedDocument, ParsedParagraph, parse_corpus_html

FIXTURE = (Path(__file__).parent / "fixtures" / "eli_sample.html").read_text()


@pytest.fixture
def docs():
    return parse_corpus_html(FIXTURE)


class TestParser:
    def test_parses_articles_and_recitals(self, docs):
        refs = {d.ref for d in docs}
        assert refs == {"Art. 1", "Art. 2", "Recital 1"}

    def test_numbered_paragraphs_with_points(self, docs):
        art1 = next(d for d in docs if d.ref == "Art. 1")
        assert art1.title == "Subject matter"
        assert [p.ref for p in art1.paragraphs] == ["Art. 1(1)", "Art. 1(2)"]
        p1 = art1.paragraphs[0].text
        assert "harmonised rules" in p1
        assert "(a) rules for placing on the market;" in p1
        assert "(b) prohibitions of certain practices." in p1

    def test_unnumbered_article_is_single_paragraph(self, docs):
        art2 = next(d for d in docs if d.ref == "Art. 2")
        assert len(art2.paragraphs) == 1
        assert art2.paragraphs[0].text.startswith("For the purposes")
        assert "Article 2" not in art2.paragraphs[0].text  # title lines stripped

    def test_recital_marker_stripped(self, docs):
        rct = next(d for d in docs if d.ref == "Recital 1")
        assert rct.paragraphs[0].text.startswith("The purpose")


class TestChunker:
    def test_context_header_prepended(self, docs):
        art1 = next(d for d in docs if d.ref == "Art. 1")
        chunks = chunk_document(art1, "Test Regulation")
        assert len(chunks) == 2
        assert chunks[0].text.startswith("[Test Regulation — Art. 1: Subject matter]\n")
        assert chunks[0].ref == "Art. 1(1)"

    def test_long_paragraph_split_respects_budget(self):
        long_text = "This is a sentence. " * 400
        doc = ParsedDocument(
            kind="article",
            ref="Art. 9",
            title="Long",
            paragraphs=[ParsedParagraph(ref="Art. 9(1)", text=long_text.strip())],
        )
        chunks = chunk_document(doc, "Test Regulation")
        assert len(chunks) > 1
        assert all(c.token_count <= MAX_CHUNK_TOKENS for c in chunks)
        assert all(c.text.startswith("[Test Regulation — Art. 9: Long]") for c in chunks)


class TestEmbeddingClient:
    async def test_batches_and_orders_responses(self, monkeypatch):
        monkeypatch.setenv("REGLENS_LLM_API_KEY", "test-key")
        from app.core.config import get_settings

        get_settings.cache_clear()
        from app.services.embeddings import EmbeddingClient

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            inputs = json.loads(request.content)["input"]
            # Return embeddings deliberately out of order to test re-sorting.
            data = [
                {"index": i, "embedding": [float(i)] * 1536} for i in reversed(range(len(inputs)))
            ]
            return httpx.Response(200, json={"data": data})

        client = EmbeddingClient()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )
        vectors = await client.embed(["a", "b", "c"])
        assert [v[0] for v in vectors] == [0.0, 1.0, 2.0]
        await client.aclose()
        get_settings.cache_clear()
