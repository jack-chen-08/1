"""商机接口：列表（含漏斗汇总）、详情、建档、强制建档、编辑、阶段推进、删除、合并、历史、阶段历程。

所有读接口都经 apply_opportunity_scope，所有出参都经金额可见性过滤；
越权对象统一 404，权限不足统一 403。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.api.duplicates import find_duplicates, project_matches
from crm.api.schemas import MergeRequest, OpportunityCreate, OpportunityPatch, StageAdvance
from crm.db import get_db
from crm.iam import CurrentUser, get_current_user, load_user
from crm.models import (
    AppUser,
    Opportunity,
    OpportunityFieldHistory,
    OpportunityMergeLog,
    OpportunityStageHistory,
    utcnow,
)
from crm.permissions.matrix_loader import get_matrix
from crm.permissions.scope import (
    apply_opportunity_scope,
    get_visible_opportunity,
    require,
    scoped_select,
    serialize_history_row,
    serialize_opportunity,
    serialize_stage_row,
    serialize_summary,
)

router = APIRouter(prefix="/api/crm/opportunities", tags=["opportunities"])

# Starlette 新版把 HTTP_422_UNPROCESSABLE_ENTITY 改名，直接用整数常量避免跨版本告警
HTTP_422 = 422

MAX_LIMIT = 100


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _assert_site_in_scope(user: CurrentUser, site_id: uuid.UUID) -> None:
    pol = get_matrix().policy(user.role)
    if pol.site_scope == "own_sites" and site_id not in user.site_id_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="site not in your data scope"
        )


def _resolve_owner(db: Session, user: CurrentUser, owner_id: str | None) -> str:
    """负责人：sales 一律落到本人；其余角色可指定，但必须是同 org 的用户。"""
    if user.role == "sales" or not owner_id:
        return user.id
    owner = db.scalar(select(AppUser).where(AppUser.id == owner_id))
    if owner is None or str(owner.org_id) != str(user.org_id):
        raise HTTPException(status_code=HTTP_422, detail="unknown owner")
    return owner_id


def _log_field(
    db: Session,
    opp: Opportunity,
    field: str,
    old,
    new,
    actor: str,
) -> None:
    db.add(
        OpportunityFieldHistory(
            opportunity_id=opp.id,
            org_id=opp.org_id,
            site_id=opp.site_id,
            field=field,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
            changed_by=actor,
        )
    )


def _build_list_filters(user, *, stage, owner_id, site_id, q) -> list:
    """列表与汇总共用同一组过滤条件，保证 summary 与 items 口径一致。"""
    filters: list = []
    if stage:
        filters.append(Opportunity.stage == stage)
    if owner_id:
        filters.append(Opportunity.owner_id == owner_id)
    if site_id:
        filters.append(Opportunity.site_id == site_id)
    if q:
        filters.append(Opportunity.company_name.ilike(f"%{q}%"))
    return filters


# --------------------------------------------------------------------------- #
# 列表 + 漏斗汇总
# --------------------------------------------------------------------------- #
@router.get("")
def list_opportunities(
    stage: str | None = None,
    owner_id: str | None = None,
    site_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """列表 + summary：数量与金额只统计当前用户可见的商机。"""
    require(user, "read")
    filters = _build_list_filters(user, stage=stage, owner_id=owner_id, site_id=site_id, q=q)

    query = scoped_select(user)
    for cond in filters:
        query = query.where(cond)
    rows = db.scalars(
        query.order_by(Opportunity.created_at.desc(), Opportunity.id).limit(limit).offset(offset)
    ).all()

    return {
        "items": [serialize_opportunity(r, user) for r in rows],
        "summary": serialize_summary(db, user, extra_filters=filters),
        "limit": limit,
        "offset": offset,
    }


# --------------------------------------------------------------------------- #
# 详情
# --------------------------------------------------------------------------- #
@router.get("/{opportunity_id}")
def get_opportunity(
    opportunity_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require(user, "read")
    opp = get_visible_opportunity(db, user, opportunity_id)
    return serialize_opportunity(opp, user)


# --------------------------------------------------------------------------- #
# 建档 / 强制建档
# --------------------------------------------------------------------------- #
@router.post("", status_code=status.HTTP_201_CREATED)
def create_opportunity(
    payload: OpportunityCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require(user, "write")
    _assert_site_in_scope(user, payload.site_id)

    duplicates = find_duplicates(
        db,
        user,
        company_name=payload.company_name,
        site_id=payload.site_id,
        space_requirement=payload.space_requirement,
    )
    if duplicates:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_conflict",
                "message": "same company or space requirement already exists on this site",
                "matches": project_matches(db, user, duplicates),
            },
        )

    return _persist_new(db, user, payload)


@router.post("/force-create", status_code=status.HTTP_201_CREATED)
def force_create_opportunity(
    payload: OpportunityCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """强制建档：跳过撞单拦截。仅 sales_lead 与 org_admin。"""
    require(user, "force_create")
    _assert_site_in_scope(user, payload.site_id)

    duplicates = find_duplicates(
        db,
        user,
        company_name=payload.company_name,
        site_id=payload.site_id,
        space_requirement=payload.space_requirement,
    )
    created = _persist_new(db, user, payload)
    created["duplicate_conflicts_overridden"] = len(duplicates)
    return created


def _persist_new(db: Session, user: CurrentUser, payload: OpportunityCreate) -> dict:
    opp = Opportunity(
        org_id=user.org_id,
        site_id=payload.site_id,
        company_name=payload.company_name,
        stage=payload.stage,
        owner_id=_resolve_owner(db, user, payload.owner_id),
        expected_first_year_amount_fen=payload.expected_first_year_amount_fen,
        weighted_amount_fen=payload.weighted_amount_fen,
        space_requirement=payload.space_requirement,
        created_by=user.id,
    )
    db.add(opp)
    db.flush()
    db.add(
        OpportunityStageHistory(
            opportunity_id=opp.id,
            org_id=opp.org_id,
            site_id=opp.site_id,
            from_stage=None,
            to_stage=opp.stage,
            changed_by=user.id,
            note="created",
        )
    )
    db.commit()
    db.refresh(opp)
    return serialize_opportunity(opp, user)


# --------------------------------------------------------------------------- #
# 编辑
# --------------------------------------------------------------------------- #
@router.patch("/{opportunity_id}")
def patch_opportunity(
    opportunity_id: uuid.UUID,
    payload: OpportunityPatch,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require(user, "write")
    opp = get_visible_opportunity(db, user, opportunity_id)

    changes = payload.model_dump(exclude_unset=True)
    # 负责人变更同样要过归属校验：sales 一律落回本人，其余角色只可指派同 org 用户
    if "owner_id" in changes:
        changes["owner_id"] = _resolve_owner(db, user, changes["owner_id"])
    for field, new in changes.items():
        old = getattr(opp, field)
        if old == new:
            continue
        setattr(opp, field, new)
        _log_field(db, opp, field, old, new, user.id)
    opp.updated_at = utcnow()
    db.commit()
    db.refresh(opp)
    return serialize_opportunity(opp, user)


# --------------------------------------------------------------------------- #
# 阶段推进
# --------------------------------------------------------------------------- #
@router.post("/{opportunity_id}/advance")
def advance_stage(
    opportunity_id: uuid.UUID,
    payload: StageAdvance,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """阶段推进：负责人本人或 sales_lead；流转边必须在 stage_graph 内。"""
    opp = get_visible_opportunity(db, user, opportunity_id)
    require(user, "advance_stage", opp)

    matrix = get_matrix()
    if not matrix.can_change_to(opp.stage, payload.to_stage):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"illegal stage transition: {opp.stage} -> {payload.to_stage}",
        )

    previous = opp.stage
    opp.stage = payload.to_stage
    opp.updated_at = utcnow()
    db.add(
        OpportunityStageHistory(
            opportunity_id=opp.id,
            org_id=opp.org_id,
            site_id=opp.site_id,
            from_stage=previous,
            to_stage=payload.to_stage,
            changed_by=user.id,
            note=payload.note,
        )
    )
    _log_field(db, opp, "stage", previous, payload.to_stage, user.id)
    db.commit()
    db.refresh(opp)
    return serialize_opportunity(opp, user)


# --------------------------------------------------------------------------- #
# 删除（软删）与合并
# --------------------------------------------------------------------------- #
@router.delete("/{opportunity_id}", status_code=status.HTTP_200_OK)
def delete_opportunity(
    opportunity_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """软删除：仅 sales_lead 与 org_admin。"""
    require(user, "delete")
    opp = get_visible_opportunity(db, user, opportunity_id)
    opp.deleted_at = utcnow()
    opp.updated_at = utcnow()
    _log_field(db, opp, "deleted_at", None, opp.deleted_at.isoformat(), user.id)
    db.commit()
    return {"id": str(opp.id), "deleted": True, "deleted_at": opp.deleted_at.isoformat()}


@router.post("/merge")
def merge_opportunities(
    payload: MergeRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """合并：source 金额并入 target，source 软删并留痕。仅 sales_lead 与 org_admin。"""
    require(user, "merge")
    if payload.source_id == payload.target_id:
        raise HTTPException(status_code=HTTP_422, detail="source == target")

    source = get_visible_opportunity(db, user, payload.source_id)
    target = get_visible_opportunity(db, user, payload.target_id)
    if source.org_id != target.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="opportunity not found")

    target.expected_first_year_amount_fen += source.expected_first_year_amount_fen
    target.weighted_amount_fen += source.weighted_amount_fen
    target.updated_at = utcnow()

    source.deleted_at = utcnow()
    source.updated_at = utcnow()

    db.add(
        OpportunityMergeLog(
            org_id=target.org_id,
            source_id=source.id,
            target_id=target.id,
            merged_by=user.id,
        )
    )
    _log_field(db, target, "merged_source", None, str(source.id), user.id)
    db.commit()
    db.refresh(target)
    return {
        "target": serialize_opportunity(target, user),
        "source_id": str(source.id),
        "source_deleted": True,
    }


# --------------------------------------------------------------------------- #
# 历史与阶段历程
# --------------------------------------------------------------------------- #
@router.get("/{opportunity_id}/history")
def opportunity_history(
    opportunity_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """字段变更历史：先按数据范围判可见（不可见 404），再按角色裁金额。"""
    require(user, "read")
    opp = get_visible_opportunity(db, user, opportunity_id)
    rows = db.scalars(
        select(OpportunityFieldHistory)
        .where(OpportunityFieldHistory.opportunity_id == opp.id)
        .order_by(OpportunityFieldHistory.changed_at.desc())
    ).all()
    return {"items": [serialize_history_row(r, user) for r in rows], "count": len(rows)}


@router.get("/{opportunity_id}/stage-timeline")
def opportunity_stage_timeline(
    opportunity_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """阶段历程：按时间正序，含建档节点。"""
    require(user, "read")
    opp = get_visible_opportunity(db, user, opportunity_id)
    rows = db.scalars(
        select(OpportunityStageHistory)
        .where(OpportunityStageHistory.opportunity_id == opp.id)
        .order_by(OpportunityStageHistory.changed_at.asc())
    ).all()
    return {"items": [serialize_stage_row(r) for r in rows], "count": len(rows)}
