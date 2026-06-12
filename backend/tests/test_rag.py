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


class TestGroupSources:
    def _chunk(self, ref, text, score=0.03, slug="gdpr"):
        import uuid as _uuid

        from app.rag.retrieval.hybrid import RetrievedChunk

        return RetrievedChunk(_uuid.uuid4(), text, ref, "Lawfulness of processing", slug, score)

    def test_merges_same_article_and_strips_embedded_headers(self):
        from app.rag.generation.grounded import group_sources

        chunks = [
            self._chunk("Art. 6", "[Regulation (EU) 2016/679 — Art. 6]\n1. First paragraph."),
            self._chunk("Art. 7", "[Regulation (EU) 2016/679 — Art. 7]\nConsent conditions."),
            self._chunk(
                "Art. 6", "[Regulation (EU) 2016/679 — Art. 6]\n2. Second paragraph.", 0.05
            ),
        ]
        grouped = group_sources(chunks)
        assert [g.ref for g in grouped] == ["Art. 6", "Art. 7"]  # first-seen order
        art6 = grouped[0]
        assert art6.text.startswith("GDPR — Art. 6: Lawfulness of processing\n")
        assert "1. First paragraph." in art6.body and "2. Second paragraph." in art6.body
        assert "[Regulation" not in art6.text  # embedded headers stripped
        assert art6.score == 0.05  # max of members

    def test_token_reduction_vs_ungrouped(self):
        from app.rag.generation.grounded import build_messages, group_sources

        long_header = (
            "[Regulation (EU) 2016/679 (General Data Protection Regulation) "
            "— Art. 6: Lawfulness of processing]"
        )
        chunks = [self._chunk("Art. 6", f"{long_header}\nParagraph {i}.") for i in range(4)]
        grouped_len = len(build_messages("q", group_sources(chunks))[1]["content"])
        # Naive prompt: every chunk as its own block with the long header.
        naive = "\n\n".join(
            f"<source id={i}>\n{c.text}\n</source>" for i, c in enumerate(chunks, 1)
        )
        assert grouped_len < len(naive) * 0.6
