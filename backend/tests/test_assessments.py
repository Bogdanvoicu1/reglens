import json
import re
import uuid

import pytest
from pydantic import ValidationError

from app.assessments.classify import (
    BatchVerdicts,
    group_batches,
    make_batch_validator,
    plan_waves,
    split_runnable,
)
from app.assessments.llm_json import StageOutputError, complete_json, extract_json
from app.assessments.profile import SystemProfile
from app.assessments.rulebook import load_rulebook
from app.services.llm import StreamResult

RULE_ID_RE = re.compile(r"- rule_id: ([a-z0-9-]+)")
OB_ID_RE = re.compile(r"(?m)^- obligation_id: ([a-z0-9-]+)$")
NEED_KEY_RE = re.compile(r"(?m)^- key: ([a-z0-9-]+)$")


def _unique_email(prefix: str) -> str:
    # Fresh tenant per test run: the assessment rate-limit window is a full
    # day, so reusing a fixed email would let ZSET entries leak across runs.
    return f"{prefix}-{uuid.uuid4().hex[:10]}@reglens.local"


PROFILE = {
    "summary": "A stub system for tests.",
    "organisation_role": "develops and sells the system",
    "ai_capabilities": "none stated",
    "eu_nexus": "EU customers",
    "personal_data": "customer emails",
    "data_subjects": "customers",
    "automated_decisions": "none",
    "sector_context": "consumer software",
    "transfers_and_hosting": "EU hosting",
    "scale": "small",
    "unknowns": ["security measures"],
}


@pytest.fixture(scope="module")
def rulebook():
    return load_rulebook()


class TestWavePlanning:
    def test_every_rule_in_exactly_one_wave(self, rulebook):
        waves = plan_waves(rulebook)
        flat = [r.id for wave in waves for r in wave]
        assert sorted(flat) == sorted(r.id for r in rulebook.rules)

    def test_wave_zero_has_only_gate_free_rules(self, rulebook):
        waves = plan_waves(rulebook)
        assert {r.id for r in waves[0]} == {r.id for r in rulebook.rules if not r.requires}
        assert {"aia-is-ai-system", "aia-gpai-provider", "gdpr-applies"} <= {r.id for r in waves[0]}

    def test_requires_always_in_earlier_wave(self, rulebook):
        waves = plan_waves(rulebook)
        wave_of = {r.id: i for i, wave in enumerate(waves) for r in wave}
        for rule in rulebook.rules:
            for dep in rule.requires:
                assert wave_of[dep] < wave_of[rule.id]

    def test_derogation_runs_after_annex3(self, rulebook):
        waves = plan_waves(rulebook)
        wave_of = {r.id: i for i, wave in enumerate(waves) for r in wave}
        assert wave_of["aia-art6-derogation"] == wave_of["aia-high-risk-annex3"] + 1

    def test_batches_are_grouped(self, rulebook):
        for wave in plan_waves(rulebook):
            for batch in group_batches(wave):
                assert len({r.group for r in batch}) == 1


class TestGating:
    def test_skips_when_gate_not_applies(self, rulebook):
        rules = [rulebook.rule("aia-prohibited-subliminal"), rulebook.rule("aia-eu-market")]
        runnable, skipped = split_runnable(rules, {"aia-is-ai-system": "does_not_apply"})
        assert runnable == []
        assert {f.rule.id for f in skipped} == {r.id for r in rules}
        assert all(f.verdict == "skipped" for f in skipped)
        assert "aia-is-ai-system" in skipped[0].reasoning

    def test_runs_when_gate_applies(self, rulebook):
        rules = [rulebook.rule("aia-prohibited-subliminal")]
        runnable, skipped = split_runnable(rules, {"aia-is-ai-system": "applies"})
        assert [r.id for r in runnable] == ["aia-prohibited-subliminal"]
        assert skipped == []

    def test_needs_info_gate_also_skips(self, rulebook):
        rules = [rulebook.rule("aia-gpai-systemic")]
        runnable, skipped = split_runnable(rules, {"aia-gpai-provider": "needs_info"})
        assert runnable == []
        assert "needs_info" in skipped[0].reasoning


class TestBatchValidation:
    def _batch(self, items) -> BatchVerdicts:
        return BatchVerdicts.model_validate({"verdicts": items})

    def _item(self, rule_id, **over):
        item = {
            "rule_id": rule_id,
            "verdict": "does_not_apply",
            "confidence": 0.9,
            "reasoning": "test",
            "citations": [],
        }
        item.update(over)
        return item

    def test_accepts_complete_batch(self, rulebook):
        rules = [rulebook.rule("gdpr-applies")]
        validate = make_batch_validator(rules, {"(gdpr) Art. 2"})
        validate(self._batch([self._item("gdpr-applies")]))

    def test_rejects_missing_or_extra_rules(self, rulebook):
        rules = [rulebook.rule("gdpr-applies"), rulebook.rule("gdpr-role-controller")]
        validate = make_batch_validator(rules, {"(gdpr) Art. 2"})
        with pytest.raises(ValueError, match="exactly these rule_ids"):
            validate(self._batch([self._item("gdpr-applies")]))
        with pytest.raises(ValueError, match="exactly these rule_ids"):
            validate(
                self._batch(
                    [
                        self._item("gdpr-applies"),
                        self._item("gdpr-role-controller"),
                        self._item("gdpr-transfers"),
                    ]
                )
            )

    def test_rejects_unknown_citation_label(self, rulebook):
        rules = [rulebook.rule("gdpr-applies")]
        validate = make_batch_validator(rules, {"(gdpr) Art. 2"})
        with pytest.raises(ValueError, match="not among the source labels"):
            validate(self._batch([self._item("gdpr-applies", citations=["(gdpr) Art. 99"])]))

    def test_applies_requires_citation(self, rulebook):
        rules = [rulebook.rule("gdpr-applies")]
        validate = make_batch_validator(rules, {"(gdpr) Art. 2"})
        with pytest.raises(ValueError, match="requires a citation"):
            validate(self._batch([self._item("gdpr-applies", verdict="applies")]))

    def test_rejects_unknown_verdict_value(self):
        with pytest.raises(ValidationError):
            self._batch([self._item("x", verdict="maybe")])

    def test_agreeing_duplicate_verdicts_collapse(self):
        batch = self._batch([self._item("x"), self._item("x", reasoning="stuttered")])
        assert len(batch.verdicts) == 1
        assert batch.verdicts[0].reasoning == "test"  # first occurrence wins

    def test_conflicting_duplicate_verdicts_rejected(self):
        with pytest.raises(ValidationError, match="conflicting duplicate"):
            self._batch(
                [
                    self._item("x"),
                    self._item("x", verdict="applies", citations=["(gdpr) Art. 2"]),
                ]
            )

    def test_paragraph_level_citations_normalize_to_document(self, rulebook):
        from app.assessments.classify import normalize_citation

        allowed = {"(gdpr) Art. 4", "(gdpr) Art. 28"}
        assert normalize_citation("(gdpr) Art. 4(7)", allowed) == "(gdpr) Art. 4"
        assert normalize_citation("(gdpr) Art. 4 (7)", allowed) == "(gdpr) Art. 4"
        assert normalize_citation("(gdpr) Art. 4, point (7)", allowed) == "(gdpr) Art. 4"
        assert normalize_citation(" (gdpr) Art. 4 ", allowed) == "(gdpr) Art. 4"
        # "Art. 44" must not match the "Art. 4" label, nor unknown sources anything
        assert normalize_citation("(gdpr) Art. 44", allowed) is None
        assert normalize_citation("(gdpr) Art. 99", allowed) is None

        rules = [rulebook.rule("gdpr-role-controller")]
        validate = make_batch_validator(rules, allowed)
        validate(
            self._batch(
                [
                    self._item(
                        "gdpr-role-controller",
                        verdict="applies",
                        citations=["(gdpr) Art. 4(7)"],
                    )
                ]
            )
        )


class TestJsonCompletion:
    def test_extract_json_tolerates_fences_and_prose(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
        assert extract_json('Here you go: {"a": {"b": 2}} hope it helps') == {"a": {"b": 2}}
        with pytest.raises(ValueError):
            extract_json("no json here")

    async def test_retries_once_then_succeeds(self):
        calls: list[list[dict]] = []

        async def llm(messages):
            calls.append(messages)
            if len(calls) == 1:
                return StreamResult(text="not json")
            return StreamResult(text=json.dumps(PROFILE))

        profile, _ = await complete_json(
            llm, [{"role": "user", "content": "x"}], SystemProfile, stage="test"
        )
        assert profile.summary == PROFILE["summary"]
        assert len(calls) == 2
        # The retry carries the invalid output and a corrective instruction.
        assert calls[1][-2]["content"] == "not json"
        assert "failed validation" in calls[1][-1]["content"]

    async def test_raises_after_second_failure(self):
        async def llm(messages):
            return StreamResult(text="still not json")

        with pytest.raises(StageOutputError):
            await complete_json(
                llm, [{"role": "user", "content": "x"}], SystemProfile, stage="test"
            )


# ---------------------------------------------------------------------------
# Engine integration (real DB, stubbed LLM)
# ---------------------------------------------------------------------------


@pytest.fixture
async def corpus_available(db_available):
    from sqlalchemy import func, select

    from app.db.models import Corpus, Document
    from app.db.session import get_engine

    async with get_engine().connect() as conn:
        n = await conn.scalar(
            select(func.count())
            .select_from(Document)
            .join(Corpus, Document.corpus_id == Corpus.id)
            .where(Corpus.slug.in_(["ai-act", "gdpr"]))
        )
    if not n:
        pytest.skip("corpora not ingested")


def make_stub_llm(
    applies: set[str] = frozenset({"gdpr-applies"}),
    broken_groups=(),
    citation_for: dict[str, str] | None = None,
    gap_status: str = "missing",
):
    """Deterministic stub covering every stage, dispatched on the system
    prompt: profile → canned PROFILE; classification → `applies` for the named
    rules (with a valid citation) else does_not_apply (garbage for a broken
    group); gap analysis → `gap_status` for each obligation; remediation → one
    item covering all need keys; executive summary → prose."""
    citation_for = citation_for or {"gdpr-applies": "(gdpr) Art. 2"}

    async def llm(messages):
        system = messages[0]["content"]
        user = messages[1]["content"] if len(messages) > 1 else ""
        if system.startswith("You extract"):
            return StreamResult(text=json.dumps(PROFILE), usage={"total_tokens": 11})
        if system.startswith("You classify"):
            rule_ids = RULE_ID_RE.findall(user)
            if any(rid in broken_groups for rid in rule_ids):
                return StreamResult(text="garbage", usage={"total_tokens": 1})
            verdicts = [
                {
                    "rule_id": rid,
                    "verdict": "applies" if rid in applies else "does_not_apply",
                    "confidence": 0.9,
                    "reasoning": "stubbed",
                    "citations": [citation_for[rid]] if rid in applies else [],
                }
                for rid in rule_ids
            ]
            return StreamResult(text=json.dumps({"verdicts": verdicts}), usage={"total_tokens": 7})
        if system.startswith("You assess whether"):
            gaps = [
                {"obligation_id": ob, "status": gap_status, "reasoning": "stubbed"}
                for ob in OB_ID_RE.findall(user)
            ]
            return StreamResult(text=json.dumps({"gaps": gaps}), usage={"total_tokens": 5})
        if system.startswith("You produce a remediation"):
            item = {
                "title": "Stub remediation",
                "description": "Do the work.",
                "priority": "high",
                "effort": "M",
                "addresses": NEED_KEY_RE.findall(user),
                "tradeoffs": "Some effort required.",
            }
            return StreamResult(text=json.dumps({"items": [item]}), usage={"total_tokens": 6})
        return StreamResult(text="Stub executive summary.", usage={"total_tokens": 4})

    return llm


async def _make_assessment(session, description="A stub description long enough to validate."):
    from app.db.models import Assessment, Tenant, User

    tenant = Tenant(name=f"test-{uuid.uuid4().hex[:8]}")
    session.add(tenant)
    await session.flush()
    user = User(id=uuid.uuid4(), tenant_id=tenant.id, email="t@reglens.local")
    session.add(user)
    assessment = Assessment(
        tenant_id=tenant.id, user_id=user.id, title="test", description=description
    )
    session.add(assessment)
    await session.commit()
    return tenant, assessment


class TestEngine:
    async def test_full_run_with_gating(self, corpus_available, rulebook):
        from sqlalchemy import select

        from app.assessments.engine import run_assessment
        from app.db.models import AssessmentFinding, AssessmentReport
        from app.db.session import get_session

        async for session in get_session():
            tenant, assessment = await _make_assessment(session)
            events = [
                e async for e in run_assessment(session, assessment, llm_complete=make_stub_llm())
            ]

            names = [e.event for e in events]
            assert names[0] == "stage_started"
            assert "profile" in names
            assert "report_ready" in names
            assert names[-1] == "assessment_completed"
            done = events[-1].data
            # gdpr-applies applies; the other 9 GDPR rules + the 2 gate-free
            # AI Act rules answer does_not_apply; all 19 gated AI Act rules skip.
            assert done["verdict_counts"] == {
                "applies": 1,
                "does_not_apply": 11,
                "needs_info": 0,
                "skipped": 19,
            }
            # gdpr-applies carries no obligations, so nothing to map or gap.
            assert done["blockers"] == []
            assert done["gap_counts"] == {"met": 0, "partial": 0, "missing": 0, "unknown": 0}
            assert done["report_version"] == 1
            assert done["usage"]["total_tokens"] > 0

            await session.refresh(assessment)
            assert assessment.status == "complete"
            assert assessment.completed_at is not None
            assert assessment.system_profile["summary"] == PROFILE["summary"]
            assert assessment.rulebook_version == rulebook.version
            assert assessment.corpus_fingerprint

            findings = (
                await session.scalars(
                    select(AssessmentFinding).where(
                        AssessmentFinding.assessment_id == assessment.id
                    )
                )
            ).all()
            assert len(findings) == 1 + len(rulebook.rules)
            applied = next(f for f in findings if f.verdict == "applies")
            assert applied.rule_id == "gdpr-applies"
            assert applied.citations == {"sources": [{"corpus": "gdpr", "ref": "Art. 2"}]}

            report = await session.scalar(
                select(AssessmentReport).where(AssessmentReport.assessment_id == assessment.id)
            )
            assert report is not None and report.version == 1
            assert report.report["executive_summary"] == "Stub executive summary."
            assert "Compliance Readiness Assessment" in report.markdown

            await session.delete(tenant)
            await session.commit()

    async def test_blocker_surfaces_in_summary(self, corpus_available):
        from app.assessments.engine import run_assessment
        from app.db.session import get_session

        stub = make_stub_llm(
            applies={"aia-is-ai-system", "aia-prohibited-subliminal"},
            citation_for={
                "aia-is-ai-system": "(ai-act) Art. 3",
                "aia-prohibited-subliminal": "(ai-act) Art. 5",
            },
        )

        async for session in get_session():
            tenant, assessment = await _make_assessment(session)
            events = [e async for e in run_assessment(session, assessment, llm_complete=stub)]
            done = events[-1].data
            assert done["blockers"] == ["aia-prohibited-subliminal"]
            blocker_event = next(
                e
                for e in events
                if e.event == "finding" and e.data["rule_id"] == "aia-prohibited-subliminal"
            )
            assert blocker_event.data["severity"] == "blocker"
            await session.delete(tenant)
            await session.commit()

    async def test_partial_salvage_on_batch_failure(self, corpus_available, rulebook):
        from app.assessments.classify import classify_batch
        from app.assessments.profile import SystemProfile
        from app.db.session import get_session

        # Always-invalid batch: controller item violates applies-needs-citation,
        # processor item is individually valid and must be salvaged.
        payload = json.dumps(
            {
                "verdicts": [
                    {
                        "rule_id": "gdpr-role-controller",
                        "verdict": "applies",
                        "confidence": 0.9,
                        "reasoning": "no citation given",
                        "citations": [],
                    },
                    {
                        "rule_id": "gdpr-role-processor",
                        "verdict": "does_not_apply",
                        "confidence": 0.8,
                        "reasoning": "fine",
                        "citations": ["(gdpr) Art. 28(3)"],
                    },
                ]
            }
        )

        async def llm(messages):
            return StreamResult(text=payload)

        rules = [rulebook.rule("gdpr-role-controller"), rulebook.rule("gdpr-role-processor")]
        async for session in get_session():
            findings, usage = await classify_batch(
                session, llm, rules, SystemProfile.model_validate(PROFILE)
            )
        by_id = {f.rule.id: f for f in findings}
        assert by_id["gdpr-role-processor"].verdict == "does_not_apply"
        assert [(c.corpus, c.ref) for c in by_id["gdpr-role-processor"].citations] == [
            ("gdpr", "Art. 28")
        ]
        assert by_id["gdpr-role-controller"].verdict == "needs_info"
        assert "requires a citation" in by_id["gdpr-role-controller"].reasoning
        assert usage == {}

    def test_salvage_drops_conflicting_duplicates_keeps_clean_items(self, rulebook):
        from app.assessments.classify import _salvage_items

        rules = [rulebook.rule("gdpr-dpia-required"), rulebook.rule("gdpr-dpo-required")]
        text = json.dumps(
            {
                "verdicts": [
                    {
                        "rule_id": "gdpr-dpia-required",
                        "verdict": "applies",
                        "confidence": 0.9,
                        "reasoning": "x",
                        "citations": ["(gdpr) Art. 35"],
                    },
                    {
                        "rule_id": "gdpr-dpia-required",
                        "verdict": "needs_info",
                        "confidence": 0.5,
                        "reasoning": "y",
                        "citations": [],
                    },
                    {
                        "rule_id": "gdpr-dpo-required",
                        "verdict": "does_not_apply",
                        "confidence": 0.8,
                        "reasoning": "z",
                        "citations": [],
                    },
                ]
            }
        )
        salvaged = _salvage_items(text, rules, {"(gdpr) Art. 35", "(gdpr) Art. 37"})
        assert set(salvaged) == {"gdpr-dpo-required"}

    async def test_invalid_batch_degrades_to_needs_info(self, corpus_available):
        from app.assessments.engine import run_assessment
        from app.db.session import get_session

        # gdpr/roles batch returns garbage twice -> needs_info, run completes;
        # rules gated on those stay skipped.
        stub = make_stub_llm(broken_groups={"gdpr-role-controller", "gdpr-role-processor"})
        async for session in get_session():
            tenant, assessment = await _make_assessment(session)
            events = [e async for e in run_assessment(session, assessment, llm_complete=stub)]
            done = events[-1].data
            assert done["status"] == "complete"
            assert done["verdict_counts"]["needs_info"] == 2
            role_event = next(
                e
                for e in events
                if e.event == "finding" and e.data["rule_id"] == "gdpr-role-controller"
            )
            assert "manual review" in role_event.data["reasoning"]
            await session.delete(tenant)
            await session.commit()

    async def test_profile_failure_marks_assessment_failed(self, corpus_available):
        from app.assessments.engine import run_assessment
        from app.db.session import get_session

        async def llm(messages):
            return StreamResult(text="garbage")

        async for session in get_session():
            tenant, assessment = await _make_assessment(session)
            events = [e async for e in run_assessment(session, assessment, llm_complete=llm)]
            assert events[-1].event == "error"
            await session.refresh(assessment)
            assert assessment.status == "failed"
            await session.delete(tenant)
            await session.commit()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class TestAssessmentApi:
    async def test_requires_auth(self, client):
        resp = await client.post("/api/v1/assessments", json={"description": "x" * 100})
        assert resp.status_code == 401

    async def test_post_streams_events_and_get_is_tenant_scoped(
        self, client, db_available, redis_available, monkeypatch
    ):
        from app.assessments.engine import AssessmentEvent
        from tests.conftest import mint_token

        async def fake_run(session, assessment, **kwargs):
            yield AssessmentEvent("stage_started", {"stage": "profile_extraction"})
            yield AssessmentEvent("assessment_completed", {"status": "complete"})

        monkeypatch.setattr("app.api.routes.assessments.run_assessment", fake_run)

        token = mint_token(email=_unique_email("assess-owner"))
        resp = await client.post(
            "/api/v1/assessments",
            json={"title": "T", "description": "A long enough description " * 5},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert "event: assessment_created" in body
        assert "event: assessment_completed" in body
        assessment_id = json.loads(
            body.split("event: assessment_created\ndata: ")[1].split("\n")[0]
        )["assessment_id"]

        listed = await client.get(
            "/api/v1/assessments", headers={"Authorization": f"Bearer {token}"}
        )
        assert assessment_id in [a["id"] for a in listed.json()]

        detail = await client.get(
            f"/api/v1/assessments/{assessment_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail.status_code == 200
        assert detail.json()["title"] == "T"

        other = mint_token(email=_unique_email("assess-other"))
        foreign = await client.get(
            f"/api/v1/assessments/{assessment_id}",
            headers={"Authorization": f"Bearer {other}"},
        )
        assert foreign.status_code == 404


# ---------------------------------------------------------------------------
# Obligation mapping (stage 3) — pure, deterministic
# ---------------------------------------------------------------------------


class TestObligationMapping:
    def test_filters_deployer_obligations_when_not_deployer(self, rulebook):
        from app.assessments.mapping import map_obligations

        verdicts = {
            "aia-is-ai-system": "applies",
            "aia-high-risk-annex3": "applies",
            "aia-role-provider": "applies",
            "aia-role-deployer": "does_not_apply",
        }
        ids = {m.obligation.id for m in map_obligations(rulebook, verdicts)}
        assert "aia-art9-risk-management" in ids  # provider duty — kept
        assert "aia-art26-deployer-duties" not in ids  # deployer duty — dropped
        assert "aia-art27-fria" not in ids

    def test_audience_unestablished_when_role_needs_info(self, rulebook):
        from app.assessments.mapping import map_obligations

        verdicts = {
            "aia-is-ai-system": "applies",
            "aia-high-risk-annex3": "applies",
            "aia-role-provider": "needs_info",
            "aia-role-deployer": "applies",
        }
        mapped = {m.obligation.id: m for m in map_obligations(rulebook, verdicts)}
        assert mapped["aia-art9-risk-management"].audience_established is False
        assert mapped["aia-art26-deployer-duties"].audience_established is True

    def test_blocker_obligation_takes_blocker_severity(self, rulebook):
        from app.assessments.mapping import map_obligations

        verdicts = {"aia-is-ai-system": "applies", "aia-prohibited-subliminal": "applies"}
        mapped = {m.obligation.id: m for m in map_obligations(rulebook, verdicts)}
        assert mapped["aia-art5-cease"].severity == "blocker"

    def test_any_audience_always_included(self, rulebook):
        from app.assessments.mapping import map_obligations

        verdicts = {"gdpr-applies": "applies", "gdpr-role-controller": "applies"}
        ids = {m.obligation.id for m in map_obligations(rulebook, verdicts)}
        assert "gdpr-art30-ropa" in ids  # audience "any"

    def test_no_obligations_without_carrying_rules(self, rulebook):
        from app.assessments.mapping import map_obligations

        assert map_obligations(rulebook, {"gdpr-applies": "applies"}) == []


class TestRemediation:
    def test_clamp_downgrades_blocker_priority_without_blocker_need(self):
        from app.assessments.remediation import RemediationItem, _clamp_priorities

        items = [
            RemediationItem(
                title="t",
                description="d",
                priority="blocker",
                effort="M",
                addresses=["gdpr-art30-ropa"],
                tradeoffs="x",
            )
        ]
        _clamp_priorities(items, blocker_keys=set())
        assert items[0].priority == "high"

    async def test_synthesis_covers_every_need_and_keeps_real_blocker(self):
        from app.assessments.remediation import RemediationNeed, plan_remediation

        async def failing_llm(messages):
            return StreamResult(text="not json")

        needs = [
            RemediationNeed(
                "aia-prohibited-emotion-workplace", "blocker", "Emotion", "d", "blocker"
            ),
            RemediationNeed("gdpr-art35-dpia", "obligation", "DPIA", "[missing] ...", "pre-market"),
        ]
        items, usage = await plan_remediation(failing_llm, needs)
        addressed = {k for item in items for k in item.addresses}
        assert {"aia-prohibited-emotion-workplace", "gdpr-art35-dpia"} <= addressed
        blocker_item = next(i for i in items if "aia-prohibited-emotion-workplace" in i.addresses)
        assert blocker_item.priority == "blocker"
        assert usage == {}


class TestReportPipeline:
    async def test_obligations_gaps_remediation_and_report(self, corpus_available):
        from sqlalchemy import select

        from app.assessments.engine import run_assessment
        from app.db.models import AssessmentReport
        from app.db.session import get_session

        stub = make_stub_llm(
            applies={"aia-is-ai-system", "aia-high-risk-annex3", "aia-role-provider"},
            citation_for={
                "aia-is-ai-system": "(ai-act) Art. 3",
                "aia-high-risk-annex3": "(ai-act) Annex III",
                "aia-role-provider": "(ai-act) Art. 3",
            },
            gap_status="missing",
        )
        async for session in get_session():
            tenant, assessment = await _make_assessment(session)
            events = [e async for e in run_assessment(session, assessment, llm_complete=stub)]
            done = events[-1].data
            assert done["status"] == "complete"
            assert done["gap_counts"]["missing"] > 0

            report = await session.scalar(
                select(AssessmentReport).where(AssessmentReport.assessment_id == assessment.id)
            )
            rep = report.report
            ob_ids = {o["id"] for o in rep["obligations"]}
            assert "aia-art9-risk-management" in ob_ids  # provider duty present
            assert "aia-art26-deployer-duties" not in ob_ids  # deployer duty filtered
            assert rep["gap_counts"]["missing"] == len(rep["obligations"])
            # Safety property: every unmet obligation is covered by remediation.
            addressed = {k for item in rep["remediation"] for k in item["addresses"]}
            assert ob_ids <= addressed
            assert "Remediation roadmap" in report.markdown
            assert "## Applicable obligations" in report.markdown

            await session.delete(tenant)
            await session.commit()


class TestAssessmentApiA2:
    async def test_report_endpoints_and_delete(
        self, client, db_available, redis_available, monkeypatch
    ):
        from app.assessments.engine import AssessmentEvent
        from app.db.models import AssessmentReport
        from tests.conftest import mint_token

        async def fake_run(session, assessment, **kwargs):
            session.add(
                AssessmentReport(
                    assessment_id=assessment.id,
                    version=1,
                    report={"title": assessment.title, "executive_summary": "ok"},
                    markdown=f"# Compliance Readiness Assessment — {assessment.title}\n\nbody",
                )
            )
            assessment.status = "complete"
            await session.commit()
            yield AssessmentEvent("assessment_completed", {"status": "complete"})

        monkeypatch.setattr("app.api.routes.assessments.run_assessment", fake_run)
        token = mint_token(email=_unique_email("report-owner"))
        h = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            "/api/v1/assessments", json={"title": "RP", "description": "x " * 60}, headers=h
        )
        aid = json.loads(resp.text.split("event: assessment_created\ndata: ")[1].split("\n")[0])[
            "assessment_id"
        ]

        rj = await client.get(f"/api/v1/assessments/{aid}/report", headers=h)
        assert rj.status_code == 200 and rj.json()["version"] == 1

        rmd = await client.get(f"/api/v1/assessments/{aid}/report.md", headers=h)
        assert rmd.status_code == 200
        assert rmd.headers["content-type"].startswith("text/markdown")
        assert "Compliance Readiness Assessment" in rmd.text

        deleted = await client.delete(f"/api/v1/assessments/{aid}", headers=h)
        assert deleted.status_code == 204
        gone = await client.get(f"/api/v1/assessments/{aid}/report", headers=h)
        assert gone.status_code == 404

    async def test_clarification_answers_flow(
        self, client, db_available, redis_available, monkeypatch
    ):
        from app.assessments.engine import AssessmentEvent
        from tests.conftest import mint_token

        async def fake_run(session, assessment, *, allow_clarification=False, **kwargs):
            answered = bool((assessment.clarification or {}).get("answers"))
            if allow_clarification and not answered:
                assessment.clarification = {
                    "questions": ["Does it run in a workplace?"],
                    "answers": None,
                }
                assessment.status = "clarifying"
                await session.commit()
                yield AssessmentEvent(
                    "clarification_needed", {"questions": ["Does it run in a workplace?"]}
                )
                return
            assessment.status = "complete"
            await session.commit()
            yield AssessmentEvent("assessment_completed", {"status": "complete"})

        monkeypatch.setattr("app.api.routes.assessments.run_assessment", fake_run)
        token = mint_token(email=_unique_email("clarify-owner"))
        h = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            "/api/v1/assessments", json={"description": "x " * 60}, headers=h
        )
        assert "event: clarification_needed" in created.text
        aid = json.loads(created.text.split("event: assessment_created\ndata: ")[1].split("\n")[0])[
            "assessment_id"
        ]

        # Answering when not yet clarifying would 409; here it is clarifying.
        answered = await client.post(
            f"/api/v1/assessments/{aid}/answers",
            json={"answers": ["Yes, in a workplace."]},
            headers=h,
        )
        assert answered.status_code == 200
        assert "event: assessment_completed" in answered.text

        detail = await client.get(f"/api/v1/assessments/{aid}", headers=h)
        assert detail.json()["status"] == "complete"

        # A second answer round is rejected (no longer clarifying).
        again = await client.post(
            f"/api/v1/assessments/{aid}/answers", json={"answers": ["x"]}, headers=h
        )
        assert again.status_code == 409

    async def test_daily_assessment_limit(self, client, db_available, redis_available, monkeypatch):
        from app.assessments.engine import AssessmentEvent
        from app.services.rate_limit import SlidingWindowLimiter
        from tests.conftest import mint_token

        async def fake_run(session, assessment, **kwargs):
            assessment.status = "complete"
            await session.commit()
            yield AssessmentEvent("assessment_completed", {"status": "complete"})

        monkeypatch.setattr("app.api.routes.assessments.run_assessment", fake_run)
        monkeypatch.setattr(
            "app.services.rate_limit._assessment_limiter",
            SlidingWindowLimiter(limit=1, window_ms=86_400_000),
        )
        token = mint_token(email=_unique_email("ratelimit-owner"))
        h = {"Authorization": f"Bearer {token}"}
        body = {"description": "x " * 60}

        first = await client.post("/api/v1/assessments", json=body, headers=h)
        assert first.status_code == 200
        second = await client.post("/api/v1/assessments", json=body, headers=h)
        assert second.status_code == 429
        assert "Retry-After" in second.headers
