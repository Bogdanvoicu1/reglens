from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthContext, get_current_user
from app.db.models import Corpus
from app.db.session import get_session

router = APIRouter(prefix="/api/v1", tags=["corpora"])


class CorpusOut(BaseModel):
    slug: str
    title: str
    version: str


@router.get("/corpora")
async def list_corpora(
    _auth: Annotated[AuthContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CorpusOut]:
    rows = await session.scalars(select(Corpus).order_by(Corpus.slug))
    return [CorpusOut.model_validate(c, from_attributes=True) for c in rows]
