"""检索：关键词检索与向量检索。

关键约束（验收标准第 5 条）：**可见范围条件必须出现在检索 SQL 里**，
不能先召回再在应用层筛。因此两条检索都先 `build_visibility_filter()`，
把它放进同一个 SELECT 的 WHERE 子句，再排序、再 LIMIT。

关键词检索用 ILIKE 子串匹配（配 pg_trgm 索引，对中文无需分词器即可工作）；
生产环境可换成 zhparser / pg_bigm 的全文检索，接口与过滤条件不变。
向量检索用 pgvector 的余弦距离，阈值与排序都在 SQL 侧完成。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from kb.embedding import embed
from kb.models import KbChunk, KbDocument
from kb.visibility import build_visibility_filter

DEFAULT_LIMIT = 20
# 余弦距离阈值。此值针对本仓库的确定性桩嵌入器（kb/embedding.py）实测标定：
# 50 条虚构查询与其目标切片的自身距离最大 0.563，故取 0.60 留余量。
# 换成真实嵌入模型时必须重新标定（模型不同，距离分布完全不同）。
DEFAULT_MAX_DISTANCE = 0.60


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    doc_title: str
    version: str
    heading_path: str
    page_no: int
    content: str
    category: str
    audience: str
    score: float | None = None
    distance: float | None = None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _base_select():
    return select(
        KbChunk.id,
        KbChunk.doc_id,
        KbChunk.content,
        KbChunk.heading_path,
        KbChunk.page_no,
        KbChunk.category,
        KbChunk.audience,
        KbDocument.title,
        KbDocument.version,
    ).join(KbDocument, KbChunk.doc_id == KbDocument.id)


def keyword_stmt(user_ctx, query: str, limit: int = DEFAULT_LIMIT, matrix=None) -> Select:
    """关键词检索语句。可见条件在 WHERE 里，先于 ORDER BY / LIMIT。"""
    pattern = f"%{_escape_like(query)}%"
    return (
        _base_select()
        .where(
            build_visibility_filter(user_ctx, matrix=matrix),
            KbChunk.content.ilike(pattern, escape="\\"),
        )
        .order_by(KbChunk.doc_id, KbChunk.chunk_index)
        .limit(limit)
    )


def vector_stmt(
    user_ctx,
    query: str,
    limit: int = DEFAULT_LIMIT,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    matrix=None,
) -> Select:
    """向量检索语句。距离阈值与排序同样在 SQL 侧，可见条件前置。"""
    query_vec = embed(query)
    distance = KbChunk.embedding.cosine_distance(query_vec)
    return (
        _base_select()
        .add_columns(distance.label("distance"))
        .where(
            build_visibility_filter(user_ctx, matrix=matrix),
            KbChunk.embedding.is_not(None),
            distance <= max_distance,
        )
        .order_by(distance)
        .limit(limit)
    )


def _rows_to_hits(rows, with_distance: bool) -> list[Hit]:
    hits: list[Hit] = []
    for row in rows:
        m = row._mapping
        distance = m.get("distance") if with_distance else None
        hits.append(
            Hit(
                chunk_id=str(m["id"]),
                doc_id=str(m["doc_id"]),
                doc_title=m["title"],
                version=m["version"],
                heading_path=m["heading_path"],
                page_no=m["page_no"],
                content=m["content"],
                category=m["category"],
                audience=m["audience"],
                distance=float(distance) if distance is not None else None,
                score=(1.0 - float(distance)) if distance is not None else None,
            )
        )
    return hits


def keyword_search(
    session: Session, user_ctx, query: str, limit: int = DEFAULT_LIMIT, matrix=None
) -> list[Hit]:
    rows = session.execute(keyword_stmt(user_ctx, query, limit, matrix)).all()
    return _rows_to_hits(rows, with_distance=False)


def vector_search(
    session: Session,
    user_ctx,
    query: str,
    limit: int = DEFAULT_LIMIT,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    matrix=None,
) -> list[Hit]:
    rows = session.execute(
        vector_stmt(user_ctx, query, limit, max_distance, matrix)
    ).all()
    return _rows_to_hits(rows, with_distance=True)


def search(
    session: Session,
    user_ctx,
    query: str,
    mode: str = "keyword",
    limit: int = DEFAULT_LIMIT,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    matrix=None,
) -> list[Hit]:
    if mode == "keyword":
        return keyword_search(session, user_ctx, query, limit, matrix)
    if mode == "vector":
        return vector_search(session, user_ctx, query, limit, max_distance, matrix)
    if mode == "hybrid":
        # 混合检索同样是两条 SQL 各自前置过滤后合并，不做应用层补筛
        kw = keyword_search(session, user_ctx, query, limit, matrix)
        vec = vector_search(session, user_ctx, query, limit, max_distance, matrix)
        merged: dict[str, Hit] = {}
        for hit in kw + vec:
            merged.setdefault(hit.chunk_id, hit)
        return list(merged.values())[:limit]
    raise ValueError(f"未知检索模式：{mode}")
