"""验收标准 5：断言两种检索 SQL 里都包含可见范围条件。

做法是把语句按 PostgreSQL 方言编译成带字面量的 SQL 文本，直接在文本里查条件原子。
这同时证明了三件事：条件确实在 SQL 里（不是应用层过滤）、两种检索都挂了、
且可见条件出现在 ORDER BY / LIMIT 之前。
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from kb.iam import UserContext
from kb.search import keyword_search, keyword_stmt, vector_stmt
from tests.factory import ORG, SITE_A, SITE_B, make_doc, make_user

import uuid

STAFF_CTX = UserContext(
    user_id=uuid.uuid4(),
    org_id=ORG,
    kind="staff",
    role="supervisor",
    rank=3,
    site_ids=(SITE_A,),
)
MEMBER_CTX = UserContext(
    user_id=uuid.uuid4(),
    org_id=ORG,
    kind="member",
    role="member",
    rank=1,
    site_ids=(SITE_A,),
)


def _sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _both_ctx_and_mode():
    for ctx in (STAFF_CTX, MEMBER_CTX):
        yield ctx, _sql(keyword_stmt(ctx, "会员日"))
        yield ctx, _sql(vector_stmt(ctx, "会员日"))


@pytest.mark.parametrize("ctx,sql", list(_both_ctx_and_mode()))
def test_common_visibility_atoms_present(ctx, sql):
    """两种检索、两种上下文，都必须带上租户、软删除、下线、audience、类别条件。"""
    assert "kb_chunk.org_id" in sql
    assert "kb_chunk.deleted_at IS NULL" in sql
    assert "kb_document.deleted_at IS NULL" in sql
    assert "kb_document.status" in sql
    assert "kb_chunk.audience IN" in sql
    assert "kb_chunk.category IN" in sql


@pytest.mark.parametrize("sql", [_sql(keyword_stmt(STAFF_CTX, "会员日")), _sql(vector_stmt(STAFF_CTX, "会员日"))])
def test_staff_sql_has_role_and_site_gates(sql):
    """员工侧：岗位交集与会所交集两道闸门都必须在 SQL 里。"""
    assert "cardinality(kb_chunk.visibility_roles)" in sql
    assert "&&" in sql  # PostgreSQL 的数组交集运算，即 overlap
    assert "cardinality(kb_chunk.visibility_sites)" in sql
    assert "'supervisor'" in sql


@pytest.mark.parametrize("sql", [_sql(keyword_stmt(MEMBER_CTX, "会员日")), _sql(vector_stmt(MEMBER_CTX, "会员日"))])
def test_member_sql_has_audience_and_site_gates(sql):
    """会员侧：只按 audience + 会所收窄，不带岗位闸门（会员没有岗位）。"""
    assert "kb_chunk.audience IN ('member')" in sql
    assert "cardinality(kb_chunk.visibility_roles)" not in sql
    assert "cardinality(kb_chunk.visibility_sites)" in sql


@pytest.mark.parametrize("sql", [_sql(keyword_stmt(STAFF_CTX, "会员日")), _sql(vector_stmt(STAFF_CTX, "会员日"))])
def test_visibility_condition_applied_before_order_and_limit(sql):
    """前置施加的结构证明：WHERE 在 ORDER BY / LIMIT 之前。"""
    upper = sql.upper()
    where_at = upper.index("WHERE")
    order_at = upper.index("ORDER BY")
    limit_at = upper.index("LIMIT")
    assert where_at < order_at < limit_at
    # 可见条件（audience IN）出现在 WHERE 之后、ORDER BY 之前
    assert where_at < upper.index("KB_CHUNK.AUDIENCE IN") < order_at


def test_vector_sql_threshold_is_in_sql():
    sql = _sql(vector_stmt(MEMBER_CTX, "会员日", max_distance=0.42))
    assert "0.42" in sql
    assert "<=>" in sql  # pgvector 余弦距离算子


def test_returned_hits_are_exactly_the_sql_rows(client, session):
    """应用层没有二次筛选：检索函数返回的行数与顺序，与 SQL 直接执行的结果完全一致。"""
    staff = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    for i in range(3):
        make_doc(
            session,
            title=f"虚构文档 {i}",
            category="faq",
            audience="member",
            chunks=[f"会员日安排说明第 {i} 版", f"会员日补充第 {i} 版"],
        )

    from sqlalchemy import select

    ctx = UserContext(
        user_id=staff.id,
        org_id=ORG,
        kind="staff",
        role="staff",
        rank=1,
        site_ids=(SITE_A,),
    )
    stmt = keyword_stmt(ctx, "会员日", limit=50)
    sql_ids = [str(r._mapping["id"]) for r in session.execute(stmt).all()]
    hit_ids = [h.chunk_id for h in keyword_search(session, ctx, "会员日", limit=50)]

    assert sql_ids, "语料为空，测不出东西"
    assert hit_ids == sql_ids
