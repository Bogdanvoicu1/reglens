import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import Computed, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_col, uuid_pk

EMBEDDING_DIM = 1536


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(50), default="free")
    created_at: Mapped[datetime] = created_at_col()


class User(Base):
    """Mirrors Supabase identities; id comes from the JWT `sub` claim."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="member")
    created_at: Mapped[datetime] = created_at_col()


class Corpus(Base):
    __tablename__ = "corpora"
    __table_args__ = (UniqueConstraint("slug", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    version: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = created_at_col()

    documents: Mapped[list["Document"]] = relationship(back_populates="corpus")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    corpus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # article | recital | annex
    ref: Mapped[str] = mapped_column(String(50))  # e.g. "Art. 6(2)", "Recital 71"
    title: Mapped[str] = mapped_column(String(500), default="")
    full_text: Mapped[str] = mapped_column(Text)

    corpus: Mapped[Corpus] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    ord: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int]
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True), nullable=True
    )

    document: Mapped[Document] = relationship(back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = created_at_col()


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None]
    created_at: Mapped[datetime] = created_at_col()


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    git_sha: Mapped[str] = mapped_column(String(40))
    dataset_version: Mapped[str] = mapped_column(String(50))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()


class Assessment(Base):
    """A compliance assessment run; profile and outputs are reproducible via
    corpus_fingerprint + rulebook_version (both set when the run starts)."""

    __tablename__ = "assessments"
    __table_args__ = (Index("ix_assessments_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft | clarifying | running | complete | failed
    description: Mapped[str] = mapped_column(Text, default="")
    system_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # {"questions": [...], "answers": [...]} — set when a clarification round runs.
    clarification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    corpus_fingerprint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rulebook_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssessmentFinding(Base):
    """One persisted stage output: a rule verdict (rule_id set) or a
    stage-level artifact like the extracted profile (rule_id null)."""

    __tablename__ = "assessment_findings"
    __table_args__ = (Index("ix_assessment_findings_assessment_ord", "assessment_id", "ord"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE")
    )
    stage: Mapped[str] = mapped_column(String(50))
    rule_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None]
    reasoning: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ord: Mapped[int]
    created_at: Mapped[datetime] = created_at_col()


class AssessmentReport(Base):
    __tablename__ = "assessment_reports"
    __table_args__ = (UniqueConstraint("assessment_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(default=1)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
