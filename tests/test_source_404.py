"""验收标准 4：无权查看的切片返回 404，且响应体与不存在的切片完全一致。

三个来源必须不可区分：不存在 / 已下线 / 无权查看。
只要有一个渠道能区分出来（状态码、detail 文案、字段多寡），就等于暴露存在性。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from tests.factory import SITE_A, SITE_B, chunks_of, make_doc, make_member, make_user
from kb.models import KbDocument


def _get(client, user, chunk_id):
    return client.get(f"/api/kb/sources/{chunk_id}", headers={"X-User-Id": str(user.id)})


def test_invisible_and_nonexistent_are_byte_identical(client, session):
    member = make_member(session, site_id=SITE_A)
    doc = make_doc(session, title="内部文档", audience="internal", chunks=["内部正文"])
    hidden_id = str(chunks_of(session, doc.id)[0].id)

    invisible = _get(client, member, hidden_id)
    nonexistent = _get(client, member, str(uuid.uuid4()))

    assert invisible.status_code == 404
    assert nonexistent.status_code == 404
    assert invisible.status_code != 403
    assert invisible.content == nonexistent.content
    assert invisible.json() == nonexistent.json() == {"detail": "not_found"}


def test_offline_document_is_indistinguishable(client, session):
    staff = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    doc = make_doc(session, title="已下线文档", status="published", chunks=["正文"])
    chunk_id = str(chunks_of(session, doc.id)[0].id)

    # 下线前可见
    assert _get(client, staff, chunk_id).status_code == 200

    doc.status = "offline"
    session.commit()

    offline = _get(client, staff, chunk_id)
    nonexistent = _get(client, staff, str(uuid.uuid4()))

    assert offline.status_code == 404
    assert offline.content == nonexistent.content


def test_soft_deleted_document_is_indistinguishable(client, session):
    staff = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    doc = make_doc(session, title="将删除文档", chunks=["正文"])
    chunk_id = str(chunks_of(session, doc.id)[0].id)

    row = session.get(KbDocument, doc.id)
    row.deleted_at = datetime.now(tz=timezone.utc)
    session.commit()

    deleted = _get(client, staff, chunk_id)
    assert deleted.status_code == 404
    assert deleted.content == _get(client, staff, str(uuid.uuid4())).content


def test_malformed_chunk_id_is_same_404(client, session):
    member = make_member(session)
    bad = _get(client, member, "not-a-uuid")
    assert bad.status_code == 404
    assert bad.content == _get(client, member, str(uuid.uuid4())).content


def test_other_site_chunk_is_404(client, session):
    staff = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    doc = make_doc(session, title="B 会所文档", sites=[SITE_B], chunks=["B 会所正文"])
    chunk_id = str(chunks_of(session, doc.id)[0].id)

    assert _get(client, staff, chunk_id).status_code == 404
    assert _get(client, staff, chunk_id).content == _get(
        client, staff, str(uuid.uuid4())
    ).content


def test_visible_response_carries_required_fields(client, session):
    """可见时返回：正文、文档标题、版本、heading_path、页码、前后各一片上下文。"""
    staff = make_user(session, role="staff", rank=1, site_ids=[SITE_A])
    doc = make_doc(
        session,
        title="虚构章节文档",
        version="v3",
        chunks=[
            {"content": "第一节正文", "heading_path": "一、总则", "page_no": 1},
            {"content": "第二节正文", "heading_path": "二、流程", "page_no": 2},
            {"content": "第三节正文", "heading_path": "三、附则", "page_no": 3},
        ],
    )
    middle = chunks_of(session, doc.id)[1]

    body = _get(client, staff, str(middle.id)).json()
    assert body["doc_title"] == "虚构章节文档"
    assert body["version"] == "v3"
    assert body["heading_path"] == "二、流程"
    assert body["page_no"] == 2
    assert body["content"] == "第二节正文"
    assert body["prev"]["content"] == "第一节正文"
    assert body["next"]["content"] == "第三节正文"

    # 边界：首片没有 prev，末片没有 next
    first = _get(client, staff, str(chunks_of(session, doc.id)[0].id)).json()
    assert first["prev"] is None and first["next"] is not None
    last = _get(client, staff, str(chunks_of(session, doc.id)[2].id)).json()
    assert last["next"] is None and last["prev"] is not None
