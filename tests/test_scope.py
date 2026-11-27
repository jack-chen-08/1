"""岗位 / 会所 / 上下文三类边界。

验收标准 1–5 之外，这几条是「过滤真的按岗位和会所生效」的正面证据，
也是变异测试 M2 / M3 / M7 的靶子：删掉对应闸门，这里必然变红。
"""

from __future__ import annotations

import uuid

import pytest

from kb.models import KbChunk
from tests.factory import SITE_A, SITE_B, SITE_C, chunks_of, make_doc, make_member, make_user


def test_role_scoped_chunk_invisible_to_other_roles(client, session):
    """visibility_roles 非空时，只有岗位命中的员工能看。"""
    staff = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    supervisor = make_user(session, role="supervisor", rank=3, site_ids=[SITE_A])
    doc = make_doc(
        session, title="主管专用", audience="internal", roles=["supervisor"], chunks=["主管正文"]
    )
    chunk_id = str(chunks_of(session, doc.id)[0].id)

    assert client.get(f"/api/kb/sources/{chunk_id}", headers={"X-User-Id": str(staff.id)}).status_code == 404
    assert client.get(f"/api/kb/sources/{chunk_id}", headers={"X-User-Id": str(supervisor.id)}).status_code == 200


def test_site_scoped_chunk_invisible_to_other_site(client, session):
    """visibility_sites 非空时，只有会所命中的员工能看。"""
    staff_a = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    staff_b = make_user(session, role="staff", rank=1, site_ids=[SITE_B])
    doc = make_doc(
        session, title="A 会所专用", audience="internal", sites=[SITE_A], chunks=["A 会所正文"]
    )
    chunk_id = str(chunks_of(session, doc.id)[0].id)

    assert client.get(f"/api/kb/sources/{chunk_id}", headers={"X-User-Id": str(staff_a.id)}).status_code == 200
    assert client.get(f"/api/kb/sources/{chunk_id}", headers={"X-User-Id": str(staff_b.id)}).status_code == 404


def test_member_site_isolation(client, session):
    """会员只能看到自己所属空间的 member 切片。"""
    member_a = make_member(session, site_id=SITE_A)
    member_c = make_member(session, site_id=SITE_C)

    in_a = make_doc(session, title="A 空间对外", category="faq", audience="member", sites=[SITE_A], chunks=["A 空间说明"])
    global_doc = make_doc(session, title="全空间对外", category="faq", audience="member", sites=[], chunks=["全空间说明"])
    in_c = make_doc(session, title="C 空间对外", category="faq", audience="member", sites=[SITE_C], chunks=["C 空间说明"])

    def _ok(user, doc):
        cid = str(chunks_of(session, doc.id)[0].id)
        return client.get(f"/api/kb/sources/{cid}", headers={"X-User-Id": str(user.id)}).status_code

    assert _ok(member_a, in_a) == 200
    assert _ok(member_a, global_doc) == 200
    assert _ok(member_a, in_c) == 404
    assert _ok(member_c, in_c) == 200
    assert _ok(member_c, in_a) == 404


def test_context_never_leaks_invisible_neighbour(client, session):
    """前后文也必须过同一道过滤。

    这里人为把中间一片改成 member、两侧留 internal（等价于「同步漏改」的病害现场），
    会员拿到中间片时，prev / next 必须是 null 而不是内部正文。
    """
    member = make_member(session, site_id=SITE_A)
    doc = make_doc(
        session,
        title="混杂文档",
        category="faq",
        audience="internal",
        chunks=["第一段内部正文", "第二段对外正文", "第三段内部正文"],
    )
    rows = chunks_of(session, doc.id)
    rows[1].audience = "member"
    session.commit()
    middle = str(rows[1].id)

    body = client.get(f"/api/kb/sources/{middle}", headers={"X-User-Id": str(member.id)}).json()
    assert body["content"] == "第二段对外正文"
    assert body["prev"] is None, "上一片属于内部内容，不得作为上下文泄露"
    assert body["next"] is None, "下一片属于内部内容，不得作为上下文泄露"


def test_tenant_isolation(client, session):
    """跨租户同 id 结构不可见。"""
    other_org = uuid.UUID("00000000-0000-4000-8000-0000000000ff")
    user = make_user(session, role="org_admin", rank=5, site_ids=[SITE_A])
    doc = make_doc(session, title="他租户文档", org_id=other_org, chunks=["他租户正文"])
    chunk_id = str(chunks_of(session, doc.id)[0].id)

    resp = client.get(f"/api/kb/sources/{chunk_id}", headers={"X-User-Id": str(user.id)})
    assert resp.status_code == 404


@pytest.mark.parametrize("role,rank,visible", [
    ("staff", 1, False),
    ("senior_staff", 2, False),
    ("supervisor", 3, True),
])
def test_pricing_gate_boundary(client, session, role, rank, visible):
    """价格类在主管这条线上正好翻转——验证 min_rank=3 的边界不是约等。"""
    user = make_user(session, role=role, rank=rank, site_ids=[SITE_A])
    doc = make_doc(session, title="虚构报价口径", category="pricing", audience="internal", chunks=["虚构正文：标准报价与折扣区间。"])
    chunk_id = str(chunks_of(session, doc.id)[0].id)

    code = client.get(f"/api/kb/sources/{chunk_id}", headers={"X-User-Id": str(user.id)}).status_code
    assert code == (200 if visible else 404)
