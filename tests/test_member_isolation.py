"""验收标准 2：会员上下文对 50 条虚构查询的召回中，内部切片数为 0。

为避免「查不到任何东西也是 0」的假绿，同一个语料下同时用员工上下文做对照：
员工必须能召回同样的内部切片，证明这些内容确实可被召回、只是被过滤掉了。
"""

from __future__ import annotations

import pytest

from kb.embedding import embed
from kb.models import KbChunk
from tests.factory import SITE_A, make_doc, make_member, make_user
from tests.spec_table import MEMBER_QUERIES

INTERNAL_PREFIX = "内部口径："
MEMBER_PREFIX = "对外口径："


@pytest.fixture()
def corpus(session):
    """10 份内部文档 + 10 份对外文档，每份 5 片，共 100 片。

    50 条查询词在这 100 片里各出现两次（内部一次、对外一次），
    所以任何一条查询，只要过滤生效，会员侧就必然少于员工侧。
    """
    qs = MEMBER_QUERIES
    assert len(qs) == 50, "验收要求 50 条虚构查询"

    internal_docs, member_docs = [], []
    for i in range(0, 50, 5):
        group = qs[i : i + 5]
        internal_docs.append(
            make_doc(
                session,
                title=f"内部手册第 {i // 5 + 1} 册",
                category="sop",
                audience="internal",
                chunks=[f"{INTERNAL_PREFIX}{q}的办理要点与责任岗位说明。" for q in group],
            )
        )
        member_docs.append(
            make_doc(
                session,
                title=f"会员指南第 {i // 5 + 1} 册",
                category="faq",
                audience="member",
                chunks=[f"{MEMBER_PREFIX}{q}的对外说明与联系方式。" for q in group],
            )
        )
    return {"internal": internal_docs, "member": member_docs}


@pytest.mark.parametrize("mode", ["keyword", "vector"])
def test_member_recall_contains_zero_internal_chunks(client, session, corpus, mode):
    member = make_member(session, site_id=SITE_A)
    headers = {"X-User-Id": str(member.id)}

    internal_hits = 0
    queries_recalled = 0
    for q in MEMBER_QUERIES:
        resp = client.post(
            "/api/kb/search", json={"query": q, "mode": mode, "limit": 50}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        hits = resp.json()["hits"]
        # 每条查询都必须真的召回「该查询对应的对外切片」，否则 0 个内部切片毫无意义
        if any(q in hit["content"] for hit in hits):
            queries_recalled += 1
        for hit in hits:
            if hit["audience"] != "member":
                internal_hits += 1
            assert INTERNAL_PREFIX not in hit["content"], f"会员召回含内部正文：{q}"

    assert internal_hits == 0, f"{internal_hits} 片内部内容被会员召回"
    assert queries_recalled == 50, f"只有 {queries_recalled}/50 条查询召回到对应内容"


@pytest.mark.parametrize("mode", ["keyword", "vector"])
def test_staff_control_group_recalls_internal_chunks(client, session, corpus, mode):
    """对照组：同样的查询，员工侧必须能召回内部切片（证明语料真的可召回）。"""
    staff = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    headers = {"X-User-Id": str(staff.id)}

    internal_recalls = 0
    member_recalls = 0
    for q in MEMBER_QUERIES:
        resp = client.post(
            "/api/kb/search", json={"query": q, "mode": mode, "limit": 50}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        hits = resp.json()["hits"]
        # 同一条查询，员工侧必须能召回内部那一片——证明语料可召回，会员侧的 0 是过滤的结果
        if any(h["audience"] == "internal" and q in h["content"] for h in hits):
            internal_recalls += 1
        if any(h["audience"] == "member" and q in h["content"] for h in hits):
            member_recalls += 1

    assert internal_recalls == 50, f"员工侧只召回到 {internal_recalls}/50 片内部内容"
    assert member_recalls == 50, f"员工侧应同时看到 member 切片，实际 {member_recalls}"
