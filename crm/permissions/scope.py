"""数据范围与金额可见性 —— 本模块的两条主入口。

    apply_opportunity_scope(query, user)   —— 给任意 select 叠加组织/场地/负责人/阶段约束
    apply_amount_visibility(payload, user) —— 给任意出参（dict）套金额可见性

设计约束：
    * 只在 select 层加 where，不做「先查全量再过滤」——避免把越权数据读进内存。
    * 越权对象的详情一律 404（不是 403），不泄露对象存在性。
    * 金额裁剪统一走一处，任何接口都不得自行拼金额字段。
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from crm.iam import CurrentUser
from crm.models import Opportunity
from crm.permissions.matrix_loader import Matrix, get_matrix

# 商机上所有金额字段（分）
AMOUNT_FIELDS = ("expected_first_year_amount_fen", "weighted_amount_fen")

# 汇总里的金额字段
SUMMARY_AMOUNT_FIELDS = ("amount_total_fen", "weighted_total_fen")


# --------------------------------------------------------------------------- #
# 数据范围
# --------------------------------------------------------------------------- #
def apply_opportunity_scope(
    query: Select,
    user: CurrentUser,
    matrix: Matrix | None = None,
    *,
    ignore_owner_scope: bool = False,
    ignore_stage_filter: bool = False,
) -> Select:
    """把当前用户的数据范围叠加到商机查询上。

    规则（与 opportunity.yaml 同源）：
        * 任何角色只看本 org，且排除软删除；
        * site_scope=own_sites 的角色只看 IAM 里挂的 site_ids；
        * owner_scope=own 的角色（sales）只看 owner_id=本人；
        * stage_in 非空时只留该阶段集合（finance 只读 won）。

    ignore_owner_scope / ignore_stage_filter 仅供撞单检查使用：
    撞单的意义就是发现「同场地、他人名下、尚未成交」的重复商机，
    若沿用 owner/stage 过滤，sales 永远撞不到单、finance 永远只看得到 won。
    该放宽不改变读权限（仍在 org + site 范围内），也不下发超出投影的字段。
    """
    m = matrix or get_matrix()
    pol = m.policy(user.role)

    scoped = query.where(
        Opportunity.org_id == user.org_id,
        Opportunity.deleted_at.is_(None),
    )

    if pol.site_scope == "own_sites":
        scoped = scoped.where(Opportunity.site_id.in_(list(user.site_ids)))

    if pol.owner_scope == "own" and not ignore_owner_scope:
        scoped = scoped.where(Opportunity.owner_id == user.id)

    if pol.stage_in and not ignore_stage_filter:
        scoped = scoped.where(Opportunity.stage.in_(list(pol.stage_in)))

    return scoped


def scoped_select(user: CurrentUser, matrix: Matrix | None = None) -> Select:
    """已套好数据范围的商机 select。"""
    return apply_opportunity_scope(select(Opportunity), user, matrix)


def get_visible_opportunity(
    db: Session,
    user: CurrentUser,
    opportunity_id: uuid.UUID | str,
    matrix: Matrix | None = None,
) -> Opportunity:
    """取一条当前用户可见的商机；不可见即 404（含不存在、跨 org、越权、已软删）。"""
    oid = opportunity_id if isinstance(opportunity_id, uuid.UUID) else uuid.UUID(str(opportunity_id))
    opp = db.scalar(scoped_select(user, matrix).where(Opportunity.id == oid))
    if opp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="opportunity not found")
    return opp


# --------------------------------------------------------------------------- #
# 动作权限
# --------------------------------------------------------------------------- #
def can(user: CurrentUser, action: str, opp: Opportunity | None = None, matrix: Matrix | None = None) -> bool:
    """动作级判定（矩阵 + 归属）。"""
    m = matrix or get_matrix()
    if action == "advance_stage":
        if opp is None:
            return False
        return m.can_advance_stage(user.role, is_owner=opp.owner_id == user.id)
    return m.can(user.role, action)


def require(user: CurrentUser, action: str, opp: Opportunity | None = None, matrix: Matrix | None = None) -> None:
    """不允许即 403。"""
    if not can(user, action, opp, matrix):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"role '{user.role}' may not perform '{action}'",
        )


# --------------------------------------------------------------------------- #
# 金额可见性
# --------------------------------------------------------------------------- #
def amounts_visible(user: CurrentUser, matrix: Matrix | None = None) -> bool:
    return (matrix or get_matrix()).policy(user.role).amounts_visible


def apply_amount_visibility(
    payload: dict[str, Any],
    user: CurrentUser,
    matrix: Matrix | None = None,
    *,
    fields: Iterable[str] = AMOUNT_FIELDS,
) -> dict[str, Any]:
    """按角色裁剪出参里的金额。

    amounts.visible=false 时：指定金额字段置 null，并打上 amount_hidden=true。
    返回新 dict，不改入参。
    """
    m = matrix or get_matrix()
    pol = m.policy(user.role)
    out = dict(payload)
    if pol.amounts_visible:
        return out

    target = set(pol.amount_null_fields) or set(fields)
    for name in fields:
        if name in out and name in target:
            out[name] = None
    out["amount_hidden"] = pol.amount_hidden_flag
    return out


def summary_amount_visible(user: CurrentUser, matrix: Matrix | None = None) -> bool:
    """汇总是否下发金额字段（viewer 直接不下发键）。"""
    return amounts_visible(user, matrix)


# --------------------------------------------------------------------------- #
# 出参组装
# --------------------------------------------------------------------------- #
def serialize_opportunity(opp: Opportunity, user: CurrentUser, matrix: Matrix | None = None) -> dict[str, Any]:
    base = {
        "id": str(opp.id),
        "org_id": str(opp.org_id),
        "site_id": str(opp.site_id),
        "company_name": opp.company_name,
        "stage": opp.stage,
        "owner_id": opp.owner_id,
        "expected_first_year_amount_fen": opp.expected_first_year_amount_fen,
        "weighted_amount_fen": opp.weighted_amount_fen,
        "space_requirement": opp.space_requirement,
        "created_at": opp.created_at.isoformat() if opp.created_at else None,
        "created_by": opp.created_by,
        "updated_at": opp.updated_at.isoformat() if opp.updated_at else None,
        "deleted_at": opp.deleted_at.isoformat() if opp.deleted_at else None,
    }
    return apply_amount_visibility(base, user, matrix)


def serialize_summary(
    db: Session,
    user: CurrentUser,
    matrix: Matrix | None = None,
    *,
    extra_filters: list | None = None,
) -> dict[str, Any]:
    """漏斗汇总：数量与金额只统计当前用户可见的商机。"""
    m = matrix or get_matrix()
    rows = scoped_select(user, m)
    for cond in extra_filters or []:
        rows = rows.where(cond)

    sub = rows.subquery()
    total_count, amount_total, weighted_total = db.execute(
        select(
            func.count(sub.c.id),
            func.coalesce(func.sum(sub.c.expected_first_year_amount_fen), 0),
            func.coalesce(func.sum(sub.c.weighted_amount_fen), 0),
        )
    ).one()

    by_stage = db.execute(
        select(sub.c.stage, func.count(sub.c.id)).group_by(sub.c.stage)
    ).all()

    summary: dict[str, Any] = {
        "count": int(total_count or 0),
        "stage_counts": {stage: int(n) for stage, n in by_stage},
    }
    if summary_amount_visible(user, m):
        summary["amount_total_fen"] = int(amount_total or 0)
        summary["weighted_total_fen"] = int(weighted_total or 0)
    return summary


def serialize_history_row(row, user: CurrentUser, matrix: Matrix | None = None) -> dict[str, Any]:
    """字段历史出参：金额类字段同样受可见性约束。"""
    m = matrix or get_matrix()
    payload = {
        "id": str(row.id),
        "field": row.field,
        "old_value": row.old_value,
        "new_value": row.new_value,
        "changed_by": row.changed_by,
        "changed_at": row.changed_at.isoformat() if row.changed_at else None,
    }
    if row.field in AMOUNT_FIELDS:
        masked = apply_amount_visibility(payload, user, m)
        if masked.get("amount_hidden"):
            masked["old_value"] = None
            masked["new_value"] = None
            return masked
    return payload


def serialize_duplicate_candidate(
    opp: Opportunity, user: CurrentUser, matrix: Matrix | None = None
) -> dict[str, Any]:
    """撞单检查的字段投影。

    规则原文：对 sales 只返回撞单商机的 id、stage 与负责人，
    不返回金额与空间需求；其他角色按全文投影。
    """
    m = matrix or get_matrix()
    fields = m.duplicate_projection(user.role)
    full = {
        "id": str(opp.id),
        "stage": opp.stage,
        "owner_id": opp.owner_id,
        "owner_name": None,  # 由调用方按 IAM 补名，缺失即 None
        "site_id": str(opp.site_id),
        "expected_first_year_amount_fen": opp.expected_first_year_amount_fen,
        "weighted_amount_fen": opp.weighted_amount_fen,
        "space_requirement": opp.space_requirement,
    }
    return {name: full.get(name) for name in fields}


def serialize_stage_row(row) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "from_stage": row.from_stage,
        "to_stage": row.to_stage,
        "changed_by": row.changed_by,
        "changed_at": row.changed_at.isoformat() if row.changed_at else None,
        "note": row.note,
    }
