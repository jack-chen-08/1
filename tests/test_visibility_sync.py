"""验收标准 3：修改文档可见范围后，同一事务内全部切片的冗余字段已更新。

两条独立性质：
  a) 成功路径——按文档条数一致地同步到全部切片；
  b) 失败路径——中途抛异常时文档与切片**都**回滚，不存在半更新状态。
     b 是「同一事务」这句话唯一可被实测的含义。
"""

from __future__ import annotations

import uuid

import pytest

from kb.api import documents as documents_api
from tests.factory import SITE_A, SITE_B, chunks_of, make_doc, make_user


def test_sync_updates_every_chunk(client, session):
    admin = make_user(session, role="site_manager", rank=4, site_ids=[SITE_A])
    doc = make_doc(
        session,
        title="虚构同步文档",
        category="sop",
        audience="internal",
        chunks=["甲段正文", "乙段正文", "丙段正文", "丁段正文"],
    )
    before = chunks_of(session, doc.id)
    assert len(before) == 4
    # 先断言「改之前确实是旧值」，否则测试可能在值本来就对的情况下假绿
    assert {c.audience for c in before} == {"internal"}
    assert {tuple(c.visibility_roles) for c in before} == {()}
    assert {tuple(c.visibility_sites) for c in before} == {()}

    resp = client.patch(
        f"/api/kb/documents/{doc.id}/visibility",
        json={
            "audience": "member",
            "visibility_roles": ["supervisor"],
            "visibility_sites": [str(SITE_B)],
        },
        headers={"X-User-Id": str(admin.id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["chunks_synced"] == 4

    session.expire_all()
    after = chunks_of(session, doc.id)
    assert len(after) == 4
    for chunk in after:
        assert chunk.audience == "member"
        assert list(chunk.visibility_roles) == ["supervisor"]
        assert [str(s) for s in chunk.visibility_sites] == [str(SITE_B)]


def test_rollback_leaves_document_and_chunks_untouched(client, session, monkeypatch):
    admin = make_user(session, role="site_manager", rank=4, site_ids=[SITE_A])
    doc = make_doc(
        session,
        title="虚构回滚文档",
        category="training",
        audience="internal",
        chunks=["甲", "乙", "丙"],
    )

    def _boom(doc_id):
        raise RuntimeError("模拟同步中途失败")

    monkeypatch.setattr(documents_api, "_post_sync_hook", _boom)

    resp = client.patch(
        f"/api/kb/documents/{doc.id}/visibility",
        json={
            "audience": "member",
            "visibility_roles": [],
            "visibility_sites": [str(SITE_B)],
        },
        headers={"X-User-Id": str(admin.id)},
    )
    assert resp.status_code == 500

    session.expire_all()
    fresh_doc = session.get(type(doc), doc.id)
    assert fresh_doc.audience == "internal"
    assert list(fresh_doc.visibility_roles) == []
    assert list(fresh_doc.visibility_sites) == []

    for chunk in chunks_of(session, doc.id):
        assert chunk.audience == "internal"
        assert list(chunk.visibility_roles) == []
        assert list(chunk.visibility_sites) == []


def test_sync_visible_effect_takes_place_immediately(client, session):
    """同步不只是字段好看：改完之后会员立刻能查到，改之前查不到。"""
    admin = make_user(session, role="site_manager", rank=4, site_ids=[SITE_A])
    member = make_user(session, role="member", rank=1, kind="member", site_ids=[SITE_A])
    doc = make_doc(
        session,
        title="虚构变更文档",
        category="faq",
        audience="internal",
        chunks=["虚构正文：会员日安排在每月第二个周五。"],
    )

    payload = {"query": "会员日安排", "mode": "keyword"}
    assert (
        client.post("/api/kb/search", json=payload, headers={"X-User-Id": str(member.id)})
        .json()["total"]
        == 0
    )

    resp = client.patch(
        f"/api/kb/documents/{doc.id}/visibility",
        json={"audience": "member", "visibility_roles": [], "visibility_sites": []},
        headers={"X-User-Id": str(admin.id)},
    )
    assert resp.status_code == 200, resp.text

    after = client.post("/api/kb/search", json=payload, headers={"X-User-Id": str(member.id)})
    assert after.json()["total"] == 1
    assert after.json()["hits"][0]["doc_id"] == str(doc.id)


def test_staff_cannot_edit_visibility(client, session):
    staff = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    doc = make_doc(session, chunks=["甲"])

    resp = client.patch(
        f"/api/kb/documents/{doc.id}/visibility",
        json={"audience": "member", "visibility_roles": [], "visibility_sites": []},
        headers={"X-User-Id": str(staff.id)},
    )
    assert resp.status_code == 403


def test_other_org_document_is_404(client, session):
    admin = make_user(session, role="org_admin", rank=5, site_ids=[SITE_A])
    resp = client.patch(
        f"/api/kb/documents/{uuid.uuid4()}/visibility",
        json={"audience": "member", "visibility_roles": [], "visibility_sites": []},
        headers={"X-User-Id": str(admin.id)},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "not_found"}
