"""Assessment engine: runs the staged pipeline for one assessment.

Stages: profile extraction → (optional clarification round) → rulebook
classification → deterministic obligation mapping → gap analysis →
remediation → report assembly. Persistence-first: each stage commits before
its event is yielded, so a dropped SSE connection loses nothing. LLM access
is an injected callable, keeping the engine deterministic under test and
provider-agnostic.
"""

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessments.classify import (
    RuleFinding,
    classify_batch,
    group_batches,
    plan_waves,
    split_runnable,
)
from app.assessments.gaps import analyse_gaps
from app.assessments.llm_json import LLMComplete
from app.assessments.mapping import map_obligations
from app.assessments.profile import extract_profile
from app.assessments.remediation import collect_needs, plan_remediation
from app.assessments.report import (
    ReportBlocker,
    build_report,
    generate_executive_summary,
    render_markdown,
)
from app.assessments.rulebook import load_rulebook
from app.assessments.schema import Rulebook
from app.core.config import get_settings
from app.db.models import Assessment, AssessmentFinding, AssessmentReport
from app.services.answer_cache import corpus_fingerprint
from app.services.llm import ChatClient

log = structlog.get_logger()

_QUESTION_PREFIX = re.compile(
    r"^(does|is|are|do|has|have|will|can)\b\s+(the\s+)?"
    r"(system|organisation|organization|service|model|product|company)?\s*",
    re.IGNORECASE,
)


@dataclass
class AssessmentEvent:
    event: str
    data: dict[str, object]


def _add_usage(total: dict[str, int], usage: dict[str, int]) -> float:
    """Accumulate token counts into `total`; return this call's USD cost.
    OpenRouter reports a per-call `cost`; other providers may omit it."""
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        total[key] = total.get(key, 0) + (usage.get(key) or 0)
    return float(usage.get("cost") or 0.0)


def _humanize_question(question: str) -> str:
    """Turn a rule's yes/no question into a short noun phrase for a heading."""
    text = _QUESTION_PREFIX.sub("", question.strip()).split("?")[0].split(",")[0].split(";")[0]
    text = text.strip().rstrip(".")
    return (text[:1].upper() + text[1:])[:120] if text else question[:120]


def _finding_event(finding: RuleFinding) -> AssessmentEvent:
    rule = finding.rule
    return AssessmentEvent(
        "finding",
        {
            "rule_id": rule.id,
            "group": rule.group,
            "verdict": finding.verdict,
            "confidence": finding.confidence,
            "reasoning": finding.reasoning,
            "citations": [{"corpus": c.corpus, "ref": c.ref} for c in finding.citations],
            "severity": rule.on_applies.severity if finding.verdict == "applies" else None,
        },
    )


def _classification_row(
    assessment_id: uuid.UUID, finding: RuleFinding, ord_: int
) -> AssessmentFinding:
    return AssessmentFinding(
        assessment_id=assessment_id,
        stage="classification",
        rule_id=finding.rule.id,
        verdict=finding.verdict,
        confidence=finding.confidence,
        reasoning=finding.reasoning,
        citations={"sources": [{"corpus": c.corpus, "ref": c.ref} for c in finding.citations]},
        ord=ord_,
    )


def _effective_description(assessment: Assessment) -> str:
    """Original description plus any answered clarification Q&A."""
    clar = assessment.clarification or {}
    answers = clar.get("answers")
    if not answers:
        return assessment.description
    qa = "\n".join(
        f"Q: {q}\nA: {a}" for q, a in zip(clar.get("questions", []), answers, strict=False)
    )
    return f"{assessment.description}\n\nClarifications:\n{qa}"


async def _next_report_version(session: AsyncSession, assessment_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(AssessmentReport.version)).where(
            AssessmentReport.assessment_id == assessment_id
        )
    )
    return (current or 0) + 1


async def run_assessment(
    session: AsyncSession,
    assessment: Assessment,
    *,
    llm_complete: LLMComplete | None = None,
    blocker_complete: LLMComplete | None = None,
    rulebook: Rulebook | None = None,
    allow_clarification: bool = False,
) -> AsyncIterator[AssessmentEvent]:
    rulebook = rulebook or load_rulebook()
    settings = get_settings()
    own_client: ChatClient | None = None
    own_summary_client: ChatClient | None = None
    own_blocker_client: ChatClient | None = None
    if llm_complete is None:
        own_client = ChatClient()
        llm_complete = own_client.complete
        # Prohibited-practice detection is the safety-critical call and needs
        # reasoning the cheap model can't reliably do (e.g. recognising that an
        # 800M-template database built from public internet images is untargeted
        # scraping); route just that batch to the stronger model.
        if blocker_complete is None:
            own_blocker_client = ChatClient(
                model=settings.assessment_blocker_model or settings.judge_model
            )
            blocker_complete = own_blocker_client.complete
    # When a caller injects only llm_complete (tests, plain eval), reuse it.
    blocker_complete = blocker_complete or llm_complete
    summary_complete = llm_complete
    if own_client is not None and settings.assessment_summary_model:
        own_summary_client = ChatClient(model=settings.assessment_summary_model)
        summary_complete = own_summary_client.complete

    total_usage: dict[str, int] = {}
    total_cost = 0.0
    try:
        assessment.status = "running"
        assessment.corpus_fingerprint = await corpus_fingerprint(session, None)
        assessment.rulebook_version = rulebook.version
        await session.commit()

        # Stage 1 — profile extraction (from the description + any clarifications)
        yield AssessmentEvent("stage_started", {"stage": "profile_extraction"})
        already_answered = bool((assessment.clarification or {}).get("answers"))
        profile, usage = await extract_profile(llm_complete, _effective_description(assessment))
        total_cost += _add_usage(total_usage, usage)
        assessment.system_profile = profile.model_dump()
        await _reset_findings(session, assessment.id)
        session.add(
            AssessmentFinding(
                assessment_id=assessment.id,
                stage="profile_extraction",
                reasoning=profile.summary,
                ord=0,
            )
        )
        await session.commit()
        yield AssessmentEvent(
            "profile", {"profile": profile.model_dump(), "unknowns": profile.unknowns}
        )

        # Clarification gate — only on the first pass, only if questions exist.
        if allow_clarification and not already_answered and profile.clarifying_questions:
            assessment.clarification = {
                "questions": profile.clarifying_questions,
                "answers": None,
            }
            assessment.status = "clarifying"
            await session.commit()
            yield AssessmentEvent(
                "clarification_needed", {"questions": profile.clarifying_questions}
            )
            return

        # Stage 2 — classification in topological waves, batched per group
        yield AssessmentEvent("stage_started", {"stage": "classification"})
        verdict_map: dict[str, str] = {}
        findings_by_rule: dict[str, RuleFinding] = {}
        ord_ = 1
        for wave in plan_waves(rulebook):
            for batch_rules in group_batches(wave):
                runnable, skipped = split_runnable(batch_rules, verdict_map)
                batch_findings = list(skipped)
                if runnable:
                    is_blocker_batch = any(r.on_applies.severity == "blocker" for r in runnable)
                    classified, usage = await classify_batch(
                        session,
                        blocker_complete if is_blocker_batch else llm_complete,
                        runnable,
                        profile,
                    )
                    total_cost += _add_usage(total_usage, usage)
                    batch_findings.extend(classified)
                for finding in batch_findings:
                    session.add(_classification_row(assessment.id, finding, ord_))
                    verdict_map[finding.rule.id] = finding.verdict
                    findings_by_rule[finding.rule.id] = finding
                    ord_ += 1
                await session.commit()
                for finding in batch_findings:
                    yield _finding_event(finding)

        verdict_counts = {
            v: sum(1 for x in verdict_map.values() if x == v)
            for v in ("applies", "does_not_apply", "needs_info", "skipped")
        }
        blocker_findings = [
            findings_by_rule[rid]
            for rid, v in verdict_map.items()
            if v == "applies" and rulebook.rule(rid).on_applies.severity == "blocker"
        ]
        blockers = [
            ReportBlocker(
                rule_id=f.rule.id,
                title=_humanize_question(f.rule.question),
                reasoning=f.reasoning,
                citations=[f"{c.corpus}:{c.ref}" for c in f.citations],
            )
            for f in sorted(blocker_findings, key=lambda f: f.rule.id)
        ]

        # Stage 3 — obligation mapping (deterministic)
        yield AssessmentEvent("stage_started", {"stage": "obligation_mapping"})
        mapped = map_obligations(rulebook, verdict_map)
        yield AssessmentEvent(
            "obligations",
            {
                "obligations": [
                    {
                        "id": m.obligation.id,
                        "title": m.obligation.title,
                        "severity": m.severity,
                        "audience": m.obligation.audience,
                        "audience_established": m.audience_established,
                    }
                    for m in mapped
                ]
            },
        )

        # Stage 4 — gap analysis
        yield AssessmentEvent("stage_started", {"stage": "gap_analysis"})
        gaps, usage = await analyse_gaps(llm_complete, mapped, profile)
        total_cost += _add_usage(total_usage, usage)
        gap_by_id = {g.obligation_id: g for g in gaps}
        for m in mapped:
            gap = gap_by_id[m.obligation.id]
            session.add(
                AssessmentFinding(
                    assessment_id=assessment.id,
                    stage="gap_analysis",
                    rule_id=m.obligation.id,
                    verdict=gap.status,
                    reasoning=gap.reasoning,
                    citations={
                        "sources": [
                            {"corpus": c.corpus, "ref": c.ref} for c in m.obligation.citations
                        ]
                    },
                    ord=ord_,
                )
            )
            ord_ += 1
        await session.commit()
        for g in gaps:
            yield AssessmentEvent("gap", {"obligation_id": g.obligation_id, "status": g.status})

        # Stage 5 — remediation & tradeoffs
        yield AssessmentEvent("stage_started", {"stage": "remediation"})
        needs = collect_needs([(b.rule_id, b.title) for b in blockers], mapped, gaps)
        remediation, usage = await plan_remediation(llm_complete, needs)
        total_cost += _add_usage(total_usage, usage)

        # Stage 6 — report assembly + executive summary + markdown
        yield AssessmentEvent("stage_started", {"stage": "report"})
        report = build_report(
            assessment_id=str(assessment.id),
            title=assessment.title,
            rulebook_version=assessment.rulebook_version,
            corpus_fingerprint=assessment.corpus_fingerprint,
            profile=profile.model_dump(),
            verdict_counts=verdict_counts,
            blockers=blockers,
            obligations=mapped,
            gaps=gaps,
            remediation=remediation,
            executive_summary="",
        )
        report.executive_summary, usage = await generate_executive_summary(summary_complete, report)
        total_cost += _add_usage(total_usage, usage)
        markdown = render_markdown(report)
        version = await _next_report_version(session, assessment.id)
        session.add(
            AssessmentReport(
                assessment_id=assessment.id,
                version=version,
                report=report.model_dump(),
                markdown=markdown,
            )
        )
        assessment.status = "complete"
        assessment.completed_at = datetime.now(UTC)
        await session.commit()

        log.info(
            "assessment_completed",
            assessment_id=str(assessment.id),
            verdict_counts=verdict_counts,
            gap_counts=report.gap_counts,
            blockers=[b.rule_id for b in blockers],
            report_version=version,
            usage=total_usage,
            cost_usd=round(total_cost, 6),
        )
        yield AssessmentEvent("report_ready", {"version": version, "report": report.model_dump()})
        yield AssessmentEvent(
            "assessment_completed",
            {
                "assessment_id": str(assessment.id),
                "status": "complete",
                "verdict_counts": verdict_counts,
                "gap_counts": report.gap_counts,
                "blockers": [b.rule_id for b in blockers],
                "report_version": version,
                "usage": total_usage,
                "cost_usd": round(total_cost, 6),
            },
        )
    except Exception:
        log.exception("assessment_failed", assessment_id=str(assessment.id))
        await session.rollback()
        assessment.status = "failed"
        await session.commit()
        yield AssessmentEvent(
            "error", {"message": "Assessment failed; partial findings were preserved."}
        )
    finally:
        if own_client is not None:
            await own_client.aclose()
        if own_summary_client is not None:
            await own_summary_client.aclose()
        if own_blocker_client is not None:
            await own_blocker_client.aclose()


async def _reset_findings(session: AsyncSession, assessment_id: uuid.UUID) -> None:
    """Clear prior findings so a clarification re-run does not duplicate them."""
    await session.execute(
        delete(AssessmentFinding).where(AssessmentFinding.assessment_id == assessment_id)
    )
