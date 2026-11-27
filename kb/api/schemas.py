"""请求 / 响应模型。"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    mode: str = Field(default="keyword", pattern="^(keyword|vector|hybrid)$")
    limit: int = Field(default=20, ge=1, le=100)


class HitOut(BaseModel):
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


class SearchResponse(BaseModel):
    mode: str
    total: int
    hits: list[HitOut]


class ContextChunkOut(BaseModel):
    chunk_id: str
    heading_path: str
    page_no: int
    content: str


class SourceResponse(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    version: str
    heading_path: str
    page_no: int
    content: str
    prev: ContextChunkOut | None = None
    next: ContextChunkOut | None = None


class VisibilityUpdate(BaseModel):
    audience: str = Field(pattern="^(internal|member)$")
    visibility_roles: list[str] = Field(default_factory=list)
    visibility_sites: list[uuid.UUID] = Field(default_factory=list)


class VisibilityUpdateResponse(BaseModel):
    doc_id: str
    audience: str
    visibility_roles: list[str]
    visibility_sites: list[str]
    chunks_synced: int
