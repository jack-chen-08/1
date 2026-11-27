"""文档可见范围修改。

要点（验收标准第 3 条）：文档与其全部切片的冗余可见范围字段**在同一事务内**更新。
实现上只用同一个 Session、只在最后 commit 一次；中途任何异常都 rollback，
不允许出现「文档已改、切片没改」的中间态。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from kb.api.schemas import VisibilityUpdate, VisibilityUpdateResponse
from kb.iam import UserContext, current_user, get_session
from kb.models import KbChunk, KbDocument, utcnow

router = APIRouter(prefix="/api/kb", tags=["kb"])

# 能改可见范围的最低岗位层级：主管（rank 3）
MIN_EDITOR_RANK = 3


def _post_sync_hook(doc_id) -> None:
    """测试注入点：在文档与切片都已更新、尚未 commit 时被调用。

    存在的目的是让「同事务」这条性质可被实测——测试让这里抛异常，
    然后断言文档和切片**都没有**被改动。
    """
    return None


@router.patch("/documents/{doc_id}/visibility", response_model=VisibilityUpdateResponse)
def update_visibility(
    doc_id: str,
    body: VisibilityUpdate,
    session: Session = Depends(get_session),
    ctx: UserContext = Depends(current_user),
):
    try:
        did = uuid.UUID(doc_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    doc = session.get(KbDocument, did)
    if doc is None or doc.deleted_at is not None or doc.org_id != ctx.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    if ctx.rank < MIN_EDITOR_RANK:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role"
        )
    # 会所负责人只能改本会所的文档；平台管理员不受限
    if ctx.rank < 5 and doc.site_id is not None and doc.site_id not in ctx.site_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="out_of_site")

    roles = list(body.visibility_roles)
    sites = [uuid.UUID(str(s)) for s in body.visibility_sites]

    try:
        doc.audience = body.audience
        doc.visibility_roles = roles
        doc.visibility_sites = sites
        doc.updated_at = utcnow()

        result = session.execute(
            update(KbChunk)
            .where(KbChunk.doc_id == doc.id)
            .values(
                audience=body.audience,
                visibility_roles=roles,
                visibility_sites=sites,
                updated_at=utcnow(),
            )
        )
        synced = int(result.rowcount or 0)

        _post_sync_hook(doc.id)
        session.commit()
    except Exception:
        # 同事务：文档改动与切片同步要么都生效，要么都不生效
        session.rollback()
        raise

    return VisibilityUpdateResponse(
        doc_id=str(doc.id),
        audience=doc.audience,
        visibility_roles=list(doc.visibility_roles),
        visibility_sites=[str(s) for s in doc.visibility_sites],
        chunks_synced=synced,
    )
