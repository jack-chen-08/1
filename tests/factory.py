"""造数工具。

所有数据都是虚构的：会所名（A/B/C 会所）、文档标题、正文均为测试构造，
不含任何真实企业名、人名、手机号、身份证或真实业务金额。
"""

from __future__ import annotations

import uuid

from kb.embedding import embed
from kb.models import AppUser, KbChunk, KbDocument

ORG = uuid.UUID("00000000-0000-4000-8000-000000000001")
SITE_A = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
SITE_B = uuid.UUID("00000000-0000-4000-8000-0000000000b2")
SITE_C = uuid.UUID("00000000-0000-4000-8000-0000000000c3")


def make_user(
    session,
    role: str = "staff",
    rank: int = 1,
    kind: str = "staff",
    site_ids=None,
    org_id=ORG,
    display_name: str = "",
) -> AppUser:
    user = AppUser(
        id=uuid.uuid4(),
        org_id=org_id,
        kind=kind,
        role=role,
        rank=rank,
        display_name=display_name or role,
        site_ids=list(site_ids if site_ids is not None else [SITE_A]),
    )
    session.add(user)
    session.commit()
    return user


def make_member(session, site_id=SITE_A, org_id=ORG) -> AppUser:
    return make_user(
        session, role="member", rank=1, kind="member", site_ids=[site_id], org_id=org_id
    )


def make_doc(
    session,
    title: str = "虚构文档",
    category: str = "sop",
    audience: str = "internal",
    roles=(),
    sites=(),
    status: str = "published",
    version: str = "v1",
    site_id=SITE_A,
    org_id=ORG,
    chunks=(),
) -> KbDocument:
    doc = KbDocument(
        id=uuid.uuid4(),
        org_id=org_id,
        site_id=site_id,
        title=title,
        version=version,
        status=status,
        audience=audience,
        visibility_roles=list(roles),
        visibility_sites=list(sites),
        category=category,
    )
    session.add(doc)
    session.flush()

    for idx, payload in enumerate(chunks):
        content = payload["content"] if isinstance(payload, dict) else str(payload)
        heading = payload.get("heading_path", f"第 {idx + 1} 节") if isinstance(payload, dict) else f"第 {idx + 1} 节"
        page = payload.get("page_no", idx + 1) if isinstance(payload, dict) else idx + 1
        session.add(
            KbChunk(
                id=uuid.uuid4(),
                org_id=doc.org_id,
                site_id=doc.site_id,
                doc_id=doc.id,
                chunk_index=idx,
                content=content,
                heading_path=heading,
                page_no=page,
                audience=doc.audience,
                visibility_roles=list(doc.visibility_roles),
                visibility_sites=list(doc.visibility_sites),
                category=doc.category,
                embedding=embed(content),
            )
        )
    session.commit()
    session.refresh(doc)
    return doc


def chunks_of(session, doc_id):
    from sqlalchemy import select

    return list(
        session.execute(
            select(KbChunk).where(KbChunk.doc_id == doc_id).order_by(KbChunk.chunk_index)
        ).scalars()
    )
