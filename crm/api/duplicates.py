"""撞单检查：同 org、同场地内按「公司名归一化」或「空间需求一致」判重。

投影差异是本接口的核心：
    sales  —— 只拿 id / stage / 负责人（不含金额、不含空间需求）
    其他角色 —— 拿完整字段
松紧口径见 crm/permissions/matrix/opportunity.yaml 的 duplicate_check_projection。
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.api.schemas import DuplicateQuery
from crm.db import get_db
from crm.iam import CurrentUser, get_current_user
from crm.models import AppUser, Opportunity
from crm.permissions.matrix_loader import get_matrix
from crm.permissions.scope import apply_opportunity_scope, serialize_duplicate_candidate

router = APIRouter(prefix="/api/crm/opportunities", tags=["duplicates"])

_WS = re.compile(r"\s+")


def normalize_company(name: str | None) -> str:
    """公司名归一化：去空白、全角括号转半角、统一小写。"""
    if not name:
        return ""
    text = _WS.sub("", str(name)).strip().casefold()
    return text.replace("（", "(").replace("）", ")")


def _owner_names(db: Session, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = db.execute(
        select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(ids))
    ).all()
    return {uid: name for uid, name in rows}


def find_duplicates(
    db: Session,
    user: CurrentUser,
    *,
    company_name: str,
    site_id: uuid.UUID,
    space_requirement: str | None = None,
    exclude_id: uuid.UUID | None = None,
) -> list[Opportunity]:
    """在「org + 可见场地」内找重复商机（不套 owner/stage 过滤，理由见 scope.py）。"""
    query = apply_opportunity_scope(
        select(Opportunity),
        user,
        ignore_owner_scope=True,
        ignore_stage_filter=True,
    ).where(Opportunity.site_id == site_id)

    if exclude_id is not None:
        query = query.where(Opportunity.id != exclude_id)

    target_company = normalize_company(company_name)
    target_space = (space_requirement or "").strip()

    matches: list[Opportunity] = []
    for row in db.scalars(query).all():
        same_company = bool(target_company) and normalize_company(row.company_name) == target_company
        same_space = bool(target_space) and (row.space_requirement or "").strip() == target_space
        if same_company or same_space:
            matches.append(row)
    return matches


def project_matches(
    db: Session, user: CurrentUser, matches: list[Opportunity]
) -> list[dict]:
    names = _owner_names(db, {m.owner_id for m in matches})
    out = []
    for row in matches:
        item = serialize_duplicate_candidate(row, user)
        if "owner_name" in item:
            item["owner_name"] = names.get(row.owner_id)
        out.append(item)
    return out


@router.post("/duplicate-check")
def duplicate_check(
    payload: DuplicateQuery,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """撞单检查：给一条待建商机，看本场地已有什么重复。"""
    matches = find_duplicates(
        db,
        user,
        company_name=payload.company_name,
        site_id=payload.site_id,
        space_requirement=payload.space_requirement,
    )
    matrix = get_matrix()
    return {
        "count": len(matches),
        "projection": list(matrix.duplicate_projection(user.role)),
        "matches": project_matches(db, user, matches),
    }


@router.get("/{opportunity_id}/duplicates")
def duplicates_of(
    opportunity_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """已存在商机的撞单视图（判重口径与上面一致）。"""
    from crm.permissions.scope import get_visible_opportunity

    opp = get_visible_opportunity(db, user, opportunity_id)
    matches = find_duplicates(
        db,
        user,
        company_name=opp.company_name,
        site_id=opp.site_id,
        space_requirement=opp.space_requirement,
        exclude_id=opp.id,
    )
    return {
        "count": len(matches),
        "projection": list(get_matrix().duplicate_projection(user.role)),
        "matches": project_matches(db, user, matches),
    }
