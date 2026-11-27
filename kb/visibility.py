"""可见范围过滤构造器 —— 本单的核心。

`build_visibility_filter(user_ctx)` 返回一个 SQLAlchemy 布尔条件，
调用方把它塞进查询的 WHERE 子句，**在数据库里前置施加**，
不存在「先召回再在应用层过滤」的路径（验收标准第 5 条即断言这一点）。

规则（与 policy/visibility_matrix.yaml 一一对应）：

员工上下文
  1. audience ∈ {internal, member}            —— 员工两类都能看
  2. visibility_roles 为空 或 与用户岗位有交集
  3. visibility_sites 为空 或 与用户会所有交集
  4. category 属于该岗位层级可访问的类别白名单
     （价格 / 政策类 min_rank=3，只对主管及以上开放）

会员上下文
  1. audience = member
  2. visibility_sites 为空 或 与会员所属空间有交集
  （会员不按岗位、不按类别收窄）

两种上下文共同的条件
  - 同一 org（租户隔离）
  - 文档未软删除、切片未软删除
  - 文档状态为 published（已下线的一律不可见，由原文接口映射成 404）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import ColumnElement, and_, func, or_

from kb.iam import MEMBER, UserContext, coerce_ctx
from kb.models import KbChunk, KbDocument
from kb.policy.loader import VisibilityMatrix, load_matrix


@dataclass(frozen=True)
class VisibilityPolicy:
    """由矩阵 + 用户上下文换算出的白名单，便于单测直接断言。"""

    kind: str
    audiences: frozenset[str]
    categories: frozenset[str]
    role_key: str | None
    site_ids: frozenset


def policy_for(user_ctx, matrix: VisibilityMatrix | None = None) -> VisibilityPolicy:
    ctx = coerce_ctx(user_ctx)
    m = matrix or load_matrix()

    if ctx.kind == MEMBER:
        return VisibilityPolicy(
            kind=MEMBER,
            audiences=frozenset(m.member_audiences),
            categories=frozenset(m.member_categories),
            role_key=None,
            site_ids=frozenset(ctx.site_ids),
        )

    rank = ctx.rank if ctx.rank > 0 else m.rank_of(ctx.role)
    # 岗位与 rank 不一致时以矩阵为准，避免调用方传错 rank 就提升权限
    rank = min(rank, m.rank_of(ctx.role)) if ctx.role in m.roles else rank
    return VisibilityPolicy(
        kind=ctx.kind,
        audiences=frozenset(m.staff_audiences),
        categories=frozenset(m.categories_for_rank(rank)),
        role_key=ctx.role,
        site_ids=frozenset(ctx.site_ids),
    )


def _array_empty_or_overlaps(column, values: Sequence):
    """Array 为空 = 不限；否则要求有交集（PostgreSQL 的 && 运算）。"""
    if not values:
        return func.cardinality(column) == 0
    return or_(func.cardinality(column) == 0, column.overlap(list(values)))


def build_visibility_filter(
    user_ctx,
    matrix: VisibilityMatrix | None = None,
    chunk=KbChunk,
    document=KbDocument,
) -> ColumnElement[bool]:
    """构造可见范围条件。chunk / document 可传入别名，便于 join 场景复用。"""
    ctx = coerce_ctx(user_ctx)
    pol = policy_for(ctx, matrix)

    conditions = [
        chunk.org_id == ctx.org_id,
        chunk.deleted_at.is_(None),
        document.deleted_at.is_(None),
        document.status == "published",
        chunk.audience.in_(tuple(sorted(pol.audiences))),
        chunk.category.in_(tuple(sorted(pol.categories))),
    ]

    if ctx.kind == MEMBER:
        conditions.append(
            _array_empty_or_overlaps(chunk.visibility_sites, tuple(pol.site_ids))
        )
    else:
        conditions.append(
            _array_empty_or_overlaps(chunk.visibility_roles, (ctx.role,))
        )
        conditions.append(
            _array_empty_or_overlaps(chunk.visibility_sites, tuple(pol.site_ids))
        )

    return and_(*conditions)


def can_view_chunk(user_ctx, chunk_id, session, matrix=None) -> bool:
    """单条可见性判断（供原文接口复用同一条件，避免两套规则漂移）。"""
    from sqlalchemy import select

    stmt = (
        select(KbChunk.id)
        .join(KbDocument, KbChunk.doc_id == KbDocument.id)
        .where(
            KbChunk.id == chunk_id,
            build_visibility_filter(user_ctx, matrix=matrix),
        )
        .limit(1)
    )
    return session.execute(stmt).first() is not None
