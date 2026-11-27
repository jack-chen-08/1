"""原文查看接口。

GET /api/kb/sources/{chunk_id}

三种情况一律 404 且响应体完全一致（不返回 403，避免暴露存在性）：
  1. 切片不存在
  2. 切片所属文档已下线 / 已软删除
  3. 切片对当前上下文不可见（audience、岗位、会所、类别任一不满足）

前后各一片上下文**同样走同一个可见条件**：相邻切片若对当前上下文不可见，
返回 null 而不是内容，避免从上下文里绕过可见范围。
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from kb.api.schemas import ContextChunkOut, SourceResponse
from kb.iam import UserContext, current_user, get_session
from kb.models import KbChunk, KbDocument
from kb.visibility import build_visibility_filter

router = APIRouter(prefix="/api/kb", tags=["kb"])

# 不存在的切片与无权查看的切片必须返回**完全相同**的响应体
NOT_FOUND_BODY = {"detail": "not_found"}


def _not_found() -> Response:
    # 手写 JSON 而不是 HTTPException：确保「不存在 / 已下线 / 无权」三条路径的
    # 响应字节完全一致，连字段顺序和空白都不给可乘之机。
    return Response(
        content=json.dumps(NOT_FOUND_BODY, separators=(",", ":"), ensure_ascii=False),
        status_code=404,
        media_type="application/json",
    )


def _fetch_visible_chunk(session: Session, ctx: UserContext, chunk_id: uuid.UUID):
    stmt = (
        select(
            KbChunk.id,
            KbChunk.doc_id,
            KbChunk.content,
            KbChunk.heading_path,
            KbChunk.page_no,
            KbChunk.chunk_index,
            KbDocument.title,
            KbDocument.version,
        )
        .join(KbDocument, KbChunk.doc_id == KbDocument.id)
        .where(
            KbChunk.id == chunk_id,
            build_visibility_filter(ctx),
        )
        .limit(1)
    )
    return session.execute(stmt).first()


def _neighbour(session: Session, ctx: UserContext, doc_id, chunk_index: int):
    stmt = (
        select(KbChunk.id, KbChunk.heading_path, KbChunk.page_no, KbChunk.content)
        .join(KbDocument, KbChunk.doc_id == KbDocument.id)
        .where(
            KbChunk.doc_id == doc_id,
            KbChunk.chunk_index == chunk_index,
            build_visibility_filter(ctx),
        )
        .limit(1)
    )
    row = session.execute(stmt).first()
    if row is None:
        return None
    m = row._mapping
    return ContextChunkOut(
        chunk_id=str(m["id"]),
        heading_path=m["heading_path"],
        page_no=m["page_no"],
        content=m["content"],
    )


@router.get("/sources/{chunk_id}", response_model=SourceResponse)
def get_source(
    chunk_id: str,
    session: Session = Depends(get_session),
    ctx: UserContext = Depends(current_user),
):
    try:
        cid = uuid.UUID(chunk_id)
    except (ValueError, AttributeError):
        return _not_found()

    row = _fetch_visible_chunk(session, ctx, cid)
    if row is None:
        return _not_found()

    m = row._mapping
    return SourceResponse(
        chunk_id=str(m["id"]),
        doc_id=str(m["doc_id"]),
        doc_title=m["title"],
        version=m["version"],
        heading_path=m["heading_path"],
        page_no=m["page_no"],
        content=m["content"],
        prev=_neighbour(session, ctx, m["doc_id"], m["chunk_index"] - 1),
        next=_neighbour(session, ctx, m["doc_id"], m["chunk_index"] + 1),
    )
