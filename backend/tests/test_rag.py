import uuid

from app.rag.generation.grounded import REFUSAL_PREFIX, build_messages, validate_answer
from app.rag.retrieval.contextualize import (
    build_contextualize_messages,
    contextualize_question,
    format_history,
    usable_rewrite,
)
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

    def test_acronym_expanded_into_fts_terms(self):
        from app.rag.retrieval.hybrid import fts_query_text

        q = fts_query_text("When is a DPIA required?")
        # The acronym never appears in the legal text; its spelled-out form does.
        for term in ("data", "protection", "impact", "assessment"):
            assert term in q.split(" OR ")
        assert "dpia" in q.split(" OR ")  # the acronym itself is still kept


class TestExpandAcronyms:
    def test_known_acronym_appends_canonical_phrase(self):
        from app.rag.retrieval.hybrid import expand_acronyms

        assert expand_acronyms("When is a DPIA required?") == (
            "When is a DPIA required? data protection impact assessment"
        )

    def test_case_insensitive_and_multiple(self):
        from app.rag.retrieval.hybrid import expand_acronyms

        out = expand_acronyms("dpo and DPIA duties")
        assert "data protection officer" in out
        assert "data protection impact assessment" in out

    def test_unknown_acronym_unchanged(self):
        from app.rag.retrieval.hybrid import expand_acronyms

        # GDPR is intentionally not expanded — its phrase is in every chunk header.
        assert expand_acronyms("What does the GDPR require?") == "What does the GDPR require?"


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


def _stub_complete(text: str = "", *, raises: bool = False):
    """A stub LLMComplete callable (no network): returns canned text or fails."""
    from app.services.llm import StreamResult

    async def complete(messages: list[dict[str, str]]) -> StreamResult:
        if raises:
            raise RuntimeError("llm down")
        return StreamResult(text=text)

    return complete


class TestContextualizeHelpers:
    def test_format_history_labels_roles(self):
        out = format_history([("user", "Are deepfakes regulated?"), ("assistant", "Yes [1].")])
        assert out == "User: Are deepfakes regulated?\nAssistant: Yes [1]."

    def test_format_history_truncates_long_turns(self):
        out = format_history([("assistant", "x" * 1500)])
        assert out.startswith("Assistant: ")
        assert out.endswith("…")
        assert len(out) < 1100  # truncated near the per-turn cap, not 1500

    def test_build_messages_carries_history_and_followup(self):
        msgs = build_contextualize_messages(
            "what about minors?",
            [("user", "Which AI practices are prohibited?"), ("assistant", "Several [1].")],
        )
        assert msgs[0]["role"] == "system"
        user = msgs[1]["content"]
        assert "Which AI practices are prohibited?" in user
        assert "Follow-up: what about minors?" in user
        assert user.rstrip().endswith("Standalone question:")

    def test_usable_rewrite_keeps_plausible(self):
        rewritten = "Which AI practices are prohibited for minors?"
        assert usable_rewrite(rewritten, "what about minors?") == rewritten

    def test_usable_rewrite_strips_wrapping_quotes(self):
        assert usable_rewrite('"What is valid consent?"', "orig") == "What is valid consent?"

    def test_usable_rewrite_empty_falls_back(self):
        assert usable_rewrite("   ", "original question") == "original question"

    def test_usable_rewrite_ramble_falls_back(self):
        assert usable_rewrite("y" * 400, "hi") == "hi"  # cap = max(300, len*4)


class TestContextualizeQuestion:
    async def test_no_history_skips_llm(self):
        calls = 0

        async def complete(messages):
            nonlocal calls
            calls += 1
            from app.services.llm import StreamResult

            return StreamResult(text="unused")

        out = await contextualize_question(complete, "What is the GDPR?", [])
        assert out == "What is the GDPR?"
        assert calls == 0

    async def test_rewrites_followup_using_history(self):
        history = [("user", "Which AI practices are prohibited?"), ("assistant", "Several [1].")]
        out = await contextualize_question(
            _stub_complete("Which AI practices are prohibited for minors?"),
            "what about minors?",
            history,
        )
        assert out == "Which AI practices are prohibited for minors?"

    async def test_llm_failure_falls_back_to_original(self):
        history = [("user", "Q"), ("assistant", "A")]
        out = await contextualize_question(
            _stub_complete(raises=True), "what about minors?", history
        )
        assert out == "what about minors?"

    async def test_blank_rewrite_falls_back_to_original(self):
        history = [("user", "Q"), ("assistant", "A")]
        out = await contextualize_question(_stub_complete("   "), "what about minors?", history)
        assert out == "what about minors?"
