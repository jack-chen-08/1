"""数据模型。

统一字段约定：id(UUID)、org_id、site_id、created_at、created_by、updated_at、deleted_at。
金额字段一律以「分」存整数（本单未涉及金额表，但约定同样适用于后续扩展）。

kb_document 是可见范围的唯一真源；kb_chunk 上的 audience / visibility_roles /
visibility_sites / category 是**冗余字段**，由文档在同一事务内同步下发，
用途是让检索 SQL 不必 join 回文档表就能前置施加过滤。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 64


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Base(DeclarativeBase):
    pass


class KbDocument(Base):
    __tablename__ = "kb_document"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    # published / offline —— 已下线的文档，其切片对任何上下文都不可见
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    # internal / member
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    visibility_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )
    visibility_sites: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_kb_document_org", "org_id"),)


class KbChunk(Base):
    __tablename__ = "kb_chunk"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    doc_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("kb_document.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    page_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # —— 以下四项是文档可见范围的冗余副本，必须与文档保持同事务一致 ——
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    visibility_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )
    visibility_sites: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="uq_kb_chunk_doc_index"),
        Index("ix_kb_chunk_org", "org_id"),
        # 关键词检索用 ILIKE 子串匹配（中文无需分词器），由 trigram GIN 索引支撑
        Index(
            "ix_kb_chunk_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
    )


class AppUser(Base):
    """S2-IAM 的接口桩：真实实现由 IAM 工单提供，本单只消费其字段。"""

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # staff / member
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="staff")
    # 员工岗位：staff / senior_staff / supervisor / site_manager / org_admin
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="staff")
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    site_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
