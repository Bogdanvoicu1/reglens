"""Assessment engine: runs the staged pipeline for one assessment.

Persistence-first: every stage output is committed before the corresponding
event is yielded, so a dropped SSE connection loses nothing — the findings
are readable via GET. LLM access is a plain injected callable, which keeps
the engine deterministic under test and provider-agnostic.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessments.classify import (
    RuleFinding,
    classify_batch,
    group_batches,
    plan_waves,
    split_runnable,
)
from app.assessments.llm_json import LLMComplete
from app.assessments.profile import extract_profile
from app.assessments.rulebook import load_rulebook
from app.assessments.schema import Rulebook
from app.db.models import Assessment, AssessmentFinding
from app.services.answer_cache import corpus_fingerprint
from app.services.llm import ChatClient

log = structlog.get_logger()


@dataclass
class AssessmentEvent:
    event: str  # stage_started | profile | finding | assessment_completed | error
    data: dict[str, object]


def _add_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        total[key] = total.get(key, 0) + (usage.get(key) or 0)


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


def _finding_row(assessment_id: uuid.UUID, finding: RuleFinding, ord_: int) -> AssessmentFinding:
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


async def run_assessment(
    session: AsyncSession,
    assessment: Assessment,
    *,
    llm_complete: LLMComplete | None = None,
    rulebook: Rulebook | None = None,
) -> AsyncIterator[AssessmentEvent]:
    rulebook = rulebook or load_rulebook()
    own_client: ChatClient | None = None
    if llm_complete is None:
        own_client = ChatClient()
        llm_complete = own_client.complete

    total_usage: dict[str, int] = {}
    try:
        assessment.status = "running"
        assessment.corpus_fingerprint = await corpus_fingerprint(session, None)
        assessment.rulebook_version = rulebook.version
        await session.commit()

        # Stage 1 — profile extraction
        yield AssessmentEvent("stage_started", {"stage": "profile_extraction"})
        profile, usage = await extract_profile(llm_complete, assessment.description)
        _add_usage(total_usage, usage)
        assessment.system_profile = profile.model_dump()
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

        # Stage 2 — classification in topological waves, batched per group
        yield AssessmentEvent("stage_started", {"stage": "classification"})
        verdict_map: dict[str, str] = {}
        ord_ = 1
        for wave in plan_waves(rulebook):
            for batch_rules in group_batches(wave):
                runnable, skipped = split_runnable(batch_rules, verdict_map)
                batch_findings = list(skipped)
                if runnable:
                    classified, usage = await classify_batch(
                        session, llm_complete, runnable, profile
                    )
                    _add_usage(total_usage, usage)
                    batch_findings.extend(classified)
                for finding in batch_findings:
                    session.add(_finding_row(assessment.id, finding, ord_))
                    verdict_map[finding.rule.id] = finding.verdict
                    ord_ += 1
                await session.commit()
                for finding in batch_findings:
                    yield _finding_event(finding)

        blockers = sorted(
            rule_id
            for rule_id, verdict in verdict_map.items()
            if verdict == "applies" and rulebook.rule(rule_id).on_applies.severity == "blocker"
        )
        counts = {
            v: sum(1 for x in verdict_map.values() if x == v)
            for v in ("applies", "does_not_apply", "needs_info", "skipped")
        }
        assessment.status = "complete"
        assessment.completed_at = datetime.now(UTC)
        await session.commit()
        log.info(
            "assessment_completed",
            assessment_id=str(assessment.id),
            counts=counts,
            blockers=blockers,
            usage=total_usage,
        )
        yield AssessmentEvent(
            "assessment_completed",
            {
                "assessment_id": str(assessment.id),
                "status": "complete",
                "verdict_counts": counts,
                "blockers": blockers,
                "usage": total_usage,
            },
        )
    except Exception:  # incl. StageOutputError from profile extraction
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
