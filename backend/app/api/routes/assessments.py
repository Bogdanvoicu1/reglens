import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.assessments.engine import run_assessment
from app.assessments.rulebook import load_rulebook
from app.core.security import AuthContext, get_current_user
from app.db.models import Assessment, AssessmentFinding
from app.db.session import get_session
from app.services.rate_limit import rate_limited_user

router = APIRouter(prefix="/api/v1", tags=["assessments"])


class AssessmentCreate(BaseModel):
    title: str = Field(default="", max_length=300)
    description: str = Field(min_length=80, max_length=8000)


class AssessmentSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    created_at: datetime
    completed_at: datetime | None


class FindingOut(BaseModel):
    stage: str
    rule_id: str | None
    group: str | None
    verdict: str | None
    confidence: float | None
    reasoning: str
    citations: dict[str, object] | None
    severity: str | None
    ord: int


class AssessmentDetail(AssessmentSummary):
    description: str
    rulebook_version: str | None
    corpus_fingerprint: str | None
    system_profile: dict[str, object] | None
    findings: list[FindingOut]


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/assessments")
async def create_assessment(
    req: AssessmentCreate,
    auth: Annotated[AuthContext, Depends(rate_limited_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    assessment = Assessment(
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        title=req.title or req.description[:120],
        description=req.description,
    )
    session.add(assessment)
    await session.commit()

    async def stream() -> AsyncIterator[str]:
        yield _sse("assessment_created", {"assessment_id": str(assessment.id)})
        async for event in run_assessment(session, assessment):
            yield _sse(event.event, event.data)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/assessments")
async def list_assessments(
    auth: Annotated[AuthContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 50,
) -> list[AssessmentSummary]:
    rows = await session.scalars(
        select(Assessment)
        .where(Assessment.tenant_id == auth.tenant_id)
        .order_by(Assessment.created_at.desc())
        .limit(min(limit, 200))
    )
    return [AssessmentSummary.model_validate(a, from_attributes=True) for a in rows]


@router.get("/assessments/{assessment_id}")
async def get_assessment(
    assessment_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentDetail:
    assessment = await session.get(Assessment, assessment_id)
    if assessment is None or assessment.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    findings = await session.scalars(
        select(AssessmentFinding)
        .where(AssessmentFinding.assessment_id == assessment_id)
        .order_by(AssessmentFinding.ord)
    )

    rules = {r.id: r for r in load_rulebook().rules}

    def out(f: AssessmentFinding) -> FindingOut:
        rule = rules.get(f.rule_id) if f.rule_id else None
        return FindingOut(
            stage=f.stage,
            rule_id=f.rule_id,
            group=rule.group if rule else None,
            verdict=f.verdict,
            confidence=f.confidence,
            reasoning=f.reasoning,
            citations=f.citations,
            severity=(rule.on_applies.severity if rule and f.verdict == "applies" else None),
            ord=f.ord,
        )

    return AssessmentDetail(
        id=assessment.id,
        title=assessment.title,
        status=assessment.status,
        created_at=assessment.created_at,
        completed_at=assessment.completed_at,
        description=assessment.description,
        rulebook_version=assessment.rulebook_version,
        corpus_fingerprint=assessment.corpus_fingerprint,
        system_profile=assessment.system_profile,
        findings=[out(f) for f in findings],
    )
