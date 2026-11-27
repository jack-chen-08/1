"""CRM 核心对象：商机（opportunity）及其留痕表。

统一字段约定（与平台技术约定一致）：
    id(UUID)、org_id、site_id、created_at、created_by、updated_at、deleted_at（软删除）
    金额一律以「分」存整数（BigInteger），不存浮点。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from crm.db import Base

# JSON 在 PG 上走 JSONB，其余方言退回通用 JSON（测试/SQLite 也能跑）
JSONType = JSON().with_variant(JSONB(), "postgresql")

STAGES = ("new", "qualified", "proposal", "won", "lost")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppUser(Base):
    """IAM 桩：身份、角色与数据范围（org_id + site_ids）。

    真实环境由 S2-IAM 提供，这里只做本地镜像表，
    字段与 IAM 对外契约一一对应，换成真实 IAM 时只改 crm/iam.py 的取数来源。
    """

    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    site_ids: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Opportunity(Base):
    """招商商机。"""

    __tablename__ = "opportunity"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # 金额：分。first_year = 预计首年金额，weighted = 按阶段权重折算后的金额
    expected_first_year_amount_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    weighted_amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # 空间需求：撞单检查用来判重，但对 sales 不下发
    space_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "stage IN ('new','qualified','proposal','won','lost')", name="ck_opportunity_stage"
        ),
        Index("ix_opportunity_org_site_stage", "org_id", "site_id", "stage"),
        Index("ix_opportunity_owner_stage", "owner_id", "stage"),
    )


class OpportunityStageHistory(Base):
    """阶段历程：每次推进留一行。"""

    __tablename__ = "opportunity_stage_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("opportunity.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    from_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)


class OpportunityFieldHistory(Base):
    """字段变更历史（金额、负责人、空间需求等）。"""

    __tablename__ = "opportunity_field_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("opportunity.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    field: Mapped[str] = mapped_column(String(60), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OpportunityMergeLog(Base):
    """合并留痕：source 被并入 target 后软删除。"""

    __tablename__ = "opportunity_merge_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    merged_by: Mapped[str] = mapped_column(String(64), nullable=False)
    merged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
