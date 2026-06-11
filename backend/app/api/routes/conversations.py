import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthContext, get_current_user
from app.db.models import Conversation, Message
from app.db.session import get_session

router = APIRouter(prefix="/api/v1", tags=["conversations"])


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: dict | None
    latency_ms: int | None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]


@router.get("/conversations")
async def list_conversations(
    auth: Annotated[AuthContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 50,
) -> list[ConversationSummary]:
    rows = await session.scalars(
        select(Conversation)
        .where(Conversation.tenant_id == auth.tenant_id)
        .order_by(Conversation.created_at.desc())
        .limit(min(limit, 200))
    )
    return [ConversationSummary.model_validate(c, from_attributes=True) for c in rows]


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationDetail:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=[MessageOut.model_validate(m, from_attributes=True) for m in messages],
    )
