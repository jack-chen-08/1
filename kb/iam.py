"""身份上下文。

S2-IAM（身份、角色与数据范围）尚未交付，本单用接口桩先行：
请求头 X-User-Id 指向 app_user 表的一行，桩负责把行映射成 UserContext。
真实接入时只需替换 `resolve_context`，其余代码不必改动（对接点见 README）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable, Mapping

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from kb.db import new_session
from kb.models import AppUser

STAFF = "staff"
MEMBER = "member"


@dataclass(frozen=True)
class UserContext:
    user_id: uuid.UUID
    org_id: uuid.UUID
    kind: str
    role: str
    rank: int
    site_ids: tuple[uuid.UUID, ...]

    @property
    def is_staff(self) -> bool:
        return self.kind == STAFF

    @property
    def is_member(self) -> bool:
        return self.kind == MEMBER

    @classmethod
    def from_mapping(cls, m: Mapping) -> "UserContext":
        site_ids = tuple(_as_uuid(s) for s in (m.get("site_ids") or ()))
        return cls(
            user_id=_as_uuid(m["user_id"]),
            org_id=_as_uuid(m["org_id"]),
            kind=str(m.get("kind", STAFF)),
            role=str(m.get("role", "staff")),
            rank=int(m.get("rank", 1)),
            site_ids=site_ids,
        )

    @classmethod
    def from_row(cls, row: AppUser) -> "UserContext":
        return cls(
            user_id=row.id,
            org_id=row.org_id,
            kind=row.kind,
            role=row.role,
            rank=row.rank,
            site_ids=tuple(row.site_ids or ()),
        )


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def coerce_ctx(user_ctx) -> UserContext:
    if isinstance(user_ctx, UserContext):
        return user_ctx
    if isinstance(user_ctx, Mapping):
        return UserContext.from_mapping(user_ctx)
    if isinstance(user_ctx, AppUser):
        return UserContext.from_row(user_ctx)
    raise TypeError(f"无法识别的用户上下文类型：{type(user_ctx)!r}")


def resolve_context(session: Session, raw_user_id: str) -> UserContext:
    """接口桩：X-User-Id → UserContext。真实 IAM 接入时替换此函数。"""
    try:
        user_id = uuid.UUID(str(raw_user_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_user")
    row = session.get(AppUser, user_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown_user")
    return UserContext.from_row(row)


def get_session() -> Iterable[Session]:
    session = new_session()
    try:
        yield session
    finally:
        session.close()


def current_user(
    x_user_id: str = Header(default="", alias="X-User-Id"),
    session: Session = Depends(get_session),
) -> UserContext:
    if not x_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_user")
    return resolve_context(session, x_user_id)
