"""检索接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kb.api.schemas import HitOut, SearchRequest, SearchResponse
from kb.iam import UserContext, current_user, get_session
from kb.search import search

router = APIRouter(prefix="/api/kb", tags=["kb"])


@router.post("/search", response_model=SearchResponse)
def do_search(
    body: SearchRequest,
    session: Session = Depends(get_session),
    ctx: UserContext = Depends(current_user),
):
    hits = search(session, ctx, body.query, mode=body.mode, limit=body.limit)
    return SearchResponse(
        mode=body.mode,
        total=len(hits),
        hits=[
            HitOut(
                chunk_id=h.chunk_id,
                doc_id=h.doc_id,
                doc_title=h.doc_title,
                version=h.version,
                heading_path=h.heading_path,
                page_no=h.page_no,
                content=h.content,
                category=h.category,
                audience=h.audience,
                score=h.score,
            )
            for h in hits
        ],
    )
