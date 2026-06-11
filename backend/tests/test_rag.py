import uuid

from app.rag.generation.grounded import REFUSAL_PREFIX, build_messages, validate_answer
from app.rag.retrieval.hybrid import RetrievedChunk, rrf_fuse


def _chunk(ref: str = "Art. 6(1)", text: str = "Processing shall be lawful…") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        text=text,
        ref=ref,
        document_title="Lawfulness of processing",
        corpus_slug="gdpr",
        score=0.05,
    )


class TestRRF:
    def test_item_in_both_rankings_outranks_single_ranking_top(self):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        scores = rrf_fuse([[a, b], [b, c]])
        assert scores[b] > scores[a]
        assert scores[b] > scores[c]

    def test_empty_rankings(self):
        assert rrf_fuse([[], []]) == {}


class TestValidation:
    def test_ok_with_valid_citations(self):
        v = validate_answer("Consent is one lawful basis [1]. See also [2].", num_sources=3)
        assert v.status == "ok"
        assert v.cited_indices == [1, 2]

    def test_refusal_detected(self):
        v = validate_answer(f"{REFUSAL_PREFIX} the sources do not cover this.", num_sources=3)
        assert v.status == "refusal"
        assert "do not cover" in v.detail

    def test_out_of_range_citation_rejected(self):
        v = validate_answer("This is stated in [7].", num_sources=3)
        assert v.status == "citation_error"

    def test_missing_citations_flagged(self):
        v = validate_answer("Consent is one lawful basis.", num_sources=3)
        assert v.status == "no_citations"


class TestPrompt:
    def test_sources_numbered_and_delimited(self):
        messages = build_messages("What makes processing lawful?", [_chunk(), _chunk("Art. 7")])
        user = messages[1]["content"]
        assert "<source id=1>" in user
        assert "<source id=2>" in user
        assert user.endswith("QUESTION: What makes processing lawful?")
        assert messages[0]["role"] == "system"


class TestFTSQuery:
    def test_words_ored_and_deduped(self):
        from app.rag.retrieval.hybrid import fts_query_text

        q = fts_query_text("Lawful bases for lawful processing under the GDPR?")
        assert q == "lawful OR bases OR for OR processing OR under OR the OR gdpr"
