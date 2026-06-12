from evals.loader import EvalEntry, ExpectedSource, load_dataset
from evals.retrieval_eval import doc_ranking, question_recall, question_rr


def _entry(refs: list[str], require: str = "any") -> EvalEntry:
    return EvalEntry(
        id="t",
        category="test",
        question="What governs lawful processing?",
        expected=[ExpectedSource(corpus="gdpr", ref=r) for r in refs],
        require=require,
    )


class TestDataset:
    def test_golden_dataset_is_valid(self):
        ds = load_dataset()
        assert ds.version == "v2"
        assert len(ds.answerable) >= 30
        assert len(ds.refusals) >= 8  # incl. red-team: extraction, injection, outside-knowledge
        valid_corpora = {"gdpr", "ai-act"}
        assert all(e.corpus in valid_corpora for entry in ds.answerable for e in entry.expected)


class TestMetrics:
    RANKING = [("gdpr", "Art. 5"), ("gdpr", "Art. 6"), ("ai-act", "Art. 9")]

    def test_recall_any_hit(self):
        assert question_recall(_entry(["Art. 6"]), self.RANKING, k=5) == 1.0
        assert question_recall(_entry(["Art. 99"]), self.RANKING, k=5) == 0.0

    def test_recall_all_partial(self):
        assert question_recall(_entry(["Art. 5", "Art. 99"], "all"), self.RANKING, k=5) == 0.5

    def test_recall_respects_k(self):
        assert question_recall(_entry(["Art. 6"]), self.RANKING, k=1) == 0.0

    def test_rr_rank_position(self):
        assert question_rr(_entry(["Art. 6"]), self.RANKING) == 0.5
        assert question_rr(_entry(["Art. 99"]), self.RANKING) == 0.0

    def test_doc_ranking_dedupes_preserving_order(self):
        import uuid

        from app.rag.retrieval.hybrid import RetrievedChunk

        def chunk(ref):
            return RetrievedChunk(uuid.uuid4(), "t", ref, "", "gdpr", 0.05)

        ranking = doc_ranking([chunk("Art. 6"), chunk("Art. 6"), chunk("Art. 5")])
        assert ranking == [("gdpr", "Art. 6"), ("gdpr", "Art. 5")]
