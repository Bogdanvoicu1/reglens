from pathlib import Path

import pytest
from pydantic import ValidationError

from app.assessments.rulebook import RULEBOOK_PATH, load_rulebook
from app.assessments.schema import Rulebook

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


@pytest.fixture(scope="module")
def rulebook():
    return load_rulebook()


def _minimal(**overrides) -> dict:
    """A valid one-rule rulebook to mutate in validator tests."""
    book = {
        "version": "test",
        "obligations": [
            {
                "id": "ob-1",
                "title": "Do the thing",
                "summary": "Summary long enough to validate.",
                "audience": "any",
                "citations": [{"corpus": "gdpr", "ref": "Art. 5"}],
            }
        ],
        "rules": [
            {
                "id": "rule-1",
                "group": "gdpr/scope",
                "question": "Is this a sufficiently long test question?",
                "retrieval_queries": ["test query"],
                "expected_sources": [{"corpus": "gdpr", "ref": "Art. 5"}],
                "on_applies": {"severity": "informational", "obligations": ["ob-1"]},
            }
        ],
    }
    book.update(overrides)
    return book


class TestRulebookContent:
    def test_loads_and_validates(self, rulebook):
        assert rulebook.version == "v1"
        assert len(rulebook.rules) >= 25
        assert len(rulebook.obligations) >= 30

    def test_both_corpora_covered(self, rulebook):
        groups = {r.group.split("/")[0] for r in rulebook.rules}
        assert groups == {"ai-act", "gdpr"}

    def test_all_prohibited_practices_are_blockers(self, rulebook):
        prohibited = [r for r in rulebook.rules if r.group == "ai-act/prohibited"]
        assert len(prohibited) == 8  # Art. 5(1)(a)-(h)
        for rule in prohibited:
            assert rule.on_applies.severity == "blocker"
            assert "aia-art5-cease" in rule.on_applies.obligations

    def test_blockers_only_from_prohibited_group(self, rulebook):
        blockers = [r for r in rulebook.rules if r.on_applies.severity == "blocker"]
        assert {r.group for r in blockers} == {"ai-act/prohibited"}

    def test_annex3_maps_full_high_risk_obligation_set(self, rulebook):
        rule = rulebook.rule("aia-high-risk-annex3")
        audiences = {rulebook.obligation(o).audience for o in rule.on_applies.obligations}
        assert audiences == {"provider", "deployer"}  # mapping stage filters by role

    def test_gpai_rules_do_not_require_ai_system(self, rulebook):
        # A GPAI model is regulated before it is integrated into any system.
        assert rulebook.rule("aia-gpai-provider").requires == []

    @pytest.mark.skipif(not RAW_DIR.exists(), reason="cached EUR-Lex HTML not present")
    def test_every_ref_exists_in_parsed_corpora(self, rulebook):
        from app.rag.ingestion.parser import parse_corpus_html
        from app.rag.ingestion.registry import CORPORA

        parsed_refs: dict[str, set[str]] = {}
        for slug, spec in CORPORA.items():
            html_path = RAW_DIR / f"{slug}-{spec.version}.html"
            if not html_path.exists():
                pytest.skip(f"missing {html_path.name}")
            parsed_refs[slug] = {d.ref for d in parse_corpus_html(html_path.read_text())}

        used = {(s.corpus, s.ref) for rule in rulebook.rules for s in rule.expected_sources} | {
            (c.corpus, c.ref) for ob in rulebook.obligations for c in ob.citations
        }
        missing = [(c, r) for c, r in sorted(used) if r not in parsed_refs[c]]
        assert not missing, f"rulebook refs not found in parsed corpora: {missing}"


class TestRulebookValidators:
    def test_unknown_obligation_rejected(self):
        book = _minimal()
        book["rules"][0]["on_applies"]["obligations"] = ["nope"]
        with pytest.raises(ValidationError, match="unknown obligations"):
            Rulebook.model_validate(book)

    def test_unreferenced_obligation_rejected(self):
        book = _minimal()
        book["rules"][0]["on_applies"]["obligations"] = []
        with pytest.raises(ValidationError, match="never referenced"):
            Rulebook.model_validate(book)

    def test_unknown_requires_rejected(self):
        book = _minimal()
        book["rules"][0]["requires"] = ["ghost-rule"]
        with pytest.raises(ValidationError, match="invalid requires"):
            Rulebook.model_validate(book)

    def test_requires_cycle_rejected(self):
        book = _minimal()
        second = dict(book["rules"][0], id="rule-2", requires=["rule-1"])
        second["on_applies"] = {"severity": "informational", "obligations": ["ob-1"]}
        book["rules"][0] = dict(book["rules"][0], requires=["rule-2"])
        book["rules"].append(second)
        with pytest.raises(ValidationError, match="requires cycle"):
            Rulebook.model_validate(book)

    def test_unknown_corpus_rejected(self):
        book = _minimal()
        book["rules"][0]["expected_sources"] = [{"corpus": "dsa", "ref": "Art. 1"}]
        with pytest.raises(ValidationError, match="Unknown corpus"):
            Rulebook.model_validate(book)

    def test_duplicate_rule_ids_rejected(self):
        book = _minimal()
        book["rules"].append(dict(book["rules"][0]))
        with pytest.raises(ValidationError, match="Duplicate rule ids"):
            Rulebook.model_validate(book)

    def test_rulebook_path_exists(self):
        assert RULEBOOK_PATH.exists()
