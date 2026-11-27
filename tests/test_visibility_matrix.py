"""验收标准 1：5 个岗位 × 6 个知识类别的权限矩阵测试。

预期来自 tests/spec_table.py（需求原文人工转写），不引用 kb.policy 的常量。
"""

from __future__ import annotations

import pytest

from kb.policy.loader import load_matrix
from tests.factory import SITE_A, chunks_of, make_doc, make_user
from tests.spec_table import (
    CATEGORIES,
    RESTRICTED_CATEGORIES,
    ROLES,
    expected_matrix,
    expected_visible,
)

RANK = {
    "staff": 1,
    "senior_staff": 2,
    "supervisor": 3,
    "site_manager": 4,
    "org_admin": 5,
}


def test_matrix_file_matches_requirement_shape():
    """矩阵文件本身的形状必须与需求原文一致：5 岗位、6 类别。"""
    m = load_matrix()
    assert sorted(m.roles) == sorted(ROLES)
    assert sorted(m.categories) == sorted(CATEGORIES)
    assert sorted(m.restricted_categories()) == sorted(RESTRICTED_CATEGORIES)
    # 「价格与政策类只对主管及以上」→ 这两类的最低层级 rank 必须等于主管的 rank
    for cat in RESTRICTED_CATEGORIES:
        assert m.categories[cat].min_rank == RANK["supervisor"]


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("role", ROLES)
def test_matrix_cell_visibility(client, session, role, category):
    """30 个格子逐格验证：可见 → 200；不可见 → 404（不是 403）。"""
    user = make_user(session, role=role, rank=RANK[role], site_ids=[SITE_A])
    doc = make_doc(
        session,
        title=f"格子-{role}-{category}",
        category=category,
        audience="internal",
        chunks=["虚构正文：本格用于验证岗位与类别的可见性组合。"],
    )
    chunk_id = str(chunks_of(session, doc.id)[0].id)

    resp = client.get(f"/api/kb/sources/{chunk_id}", headers={"X-User-Id": str(user.id)})

    if expected_visible(role, category):
        assert resp.status_code == 200, f"{role}×{category} 应可见，实际 {resp.status_code}"
        assert resp.json()["chunk_id"] == chunk_id
    else:
        assert resp.status_code == 404, f"{role}×{category} 应不可见，实际 {resp.status_code}"
        assert resp.json() == {"detail": "not_found"}


def test_matrix_has_both_visible_and_invisible_cells():
    """防止「全可见」这种塌缩：30 格里必须同时存在可见与不可见。"""
    table = expected_matrix()
    assert len(table) == 30
    assert sum(1 for v in table.values() if v) == 26
    assert sum(1 for v in table.values() if not v) == 4


@pytest.mark.parametrize("mode", ["keyword", "vector"])
def test_search_respects_category_gate(client, session, mode):
    """检索接口与原文接口同一套规则：staff 搜不到政策类，supervisor 搜得到。"""
    staff = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    supervisor = make_user(session, role="supervisor", rank=3, site_ids=[SITE_A])
    doc = make_doc(
        session,
        title="虚构政策说明",
        category="policy",
        audience="internal",
        chunks=["续费政策按会员等级分档执行。"],
    )

    payload = {"query": "续费政策", "mode": mode}
    as_staff = client.post(
        "/api/kb/search", json=payload, headers={"X-User-Id": str(staff.id)}
    )
    as_supervisor = client.post(
        "/api/kb/search", json=payload, headers={"X-User-Id": str(supervisor.id)}
    )

    assert as_staff.status_code == 200 and as_supervisor.status_code == 200
    assert as_staff.json()["total"] == 0
    assert as_supervisor.json()["total"] == 1
    assert as_supervisor.json()["hits"][0]["doc_id"] == str(doc.id)
