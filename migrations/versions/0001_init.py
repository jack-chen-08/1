"""initial schema: crm opportunity scope

Revision ID: 0001_init
Revises:
Create Date: 2026-11-27

统一字段约定：id(UUID)、org_id、site_id、created_at、created_by、updated_at、deleted_at。
金额以「分」存 BigInteger。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector：本模块的判重当前走确定性规则（公司名归一化 / 空间需求一致），
    # 该扩展为后续语义相似度去重预留，建库时一并启用。
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "app_user",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("site_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_app_user_org_id", "app_user", ["org_id"])

    op.create_table(
        "opportunity",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("expected_first_year_amount_fen", sa.BigInteger(), nullable=False),
        sa.Column("weighted_amount_fen", sa.BigInteger(), nullable=False),
        sa.Column("space_requirement", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "stage IN ('new','qualified','proposal','won','lost')",
            name="ck_opportunity_stage",
        ),
    )
    op.create_index("ix_opportunity_org_id", "opportunity", ["org_id"])
    op.create_index("ix_opportunity_site_id", "opportunity", ["site_id"])
    op.create_index("ix_opportunity_company_name", "opportunity", ["company_name"])
    op.create_index("ix_opportunity_owner_id", "opportunity", ["owner_id"])
    op.create_index("ix_opportunity_org_site_stage", "opportunity", ["org_id", "site_id", "stage"])
    op.create_index("ix_opportunity_owner_stage", "opportunity", ["owner_id", "stage"])

    op.create_table(
        "opportunity_stage_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("opportunity_id", sa.Uuid(),
                  sa.ForeignKey("opportunity.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("from_stage", sa.String(length=20), nullable=True),
        sa.Column("to_stage", sa.String(length=20), nullable=False),
        sa.Column("changed_by", sa.String(length=64), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("note", sa.String(length=400), nullable=True),
    )
    op.create_index("ix_opportunity_stage_history_opportunity_id", "opportunity_stage_history",
                    ["opportunity_id"])

    op.create_table(
        "opportunity_field_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("opportunity_id", sa.Uuid(),
                  sa.ForeignKey("opportunity.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=60), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=64), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_opportunity_field_history_opportunity_id", "opportunity_field_history",
                    ["opportunity_id"])

    op.create_table(
        "opportunity_merge_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("merged_by", sa.String(length=64), nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_opportunity_merge_log_source_id", "opportunity_merge_log", ["source_id"])
    op.create_index("ix_opportunity_merge_log_target_id", "opportunity_merge_log", ["target_id"])


def downgrade() -> None:
    op.drop_table("opportunity_merge_log")
    op.drop_table("opportunity_field_history")
    op.drop_table("opportunity_stage_history")
    op.drop_index("ix_opportunity_owner_stage", table_name="opportunity")
    op.drop_index("ix_opportunity_org_site_stage", table_name="opportunity")
    op.drop_table("opportunity")
    op.drop_table("app_user")
