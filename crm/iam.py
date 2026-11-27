"""IAM 桩：把身份、角色、数据范围（org_id + site_ids）注入请求。

真实环境由 S2-IAM 提供。本桩保持与 IAM 对外契约一致：
    用户 → { id, org_id, role, site_ids }
因此接入真实 IAM 时只需替换 `load_user()` 的取数来源，权限层与接口层不动。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.db import get_db
from crm.models import AppUser


@dataclass(frozen=True)
class CurrentUser:
    """请求上下文中的当前用户。"""

    id: str
    org_id: uuid.UUID
    role: str
    site_ids: tuple[uuid.UUID, ...]
    display_name: str

    @property
    def site_id_set(self) -> set[uuid.UUID]:
        return set(self.site_ids)


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def load_user(db: Session, user_id: str) -> CurrentUser:
    """按用户 id 取身份；不存在即 401（不泄露存在性）。"""
    row = db.scalar(select(AppUser).where(AppUser.id == user_id))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unknown user",
            headers={"WWW-Authenticate": "X-User-Id"},
        )
    return CurrentUser(
        id=row.id,
        org_id=_as_uuid(row.org_id),
        role=row.role,
        site_ids=tuple(_as_uuid(s) for s in (row.site_ids or [])),
        display_name=row.display_name,
    )


def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """FastAPI 依赖：X-User-Id → 当前用户。

    桩环境用请求头直接给用户 id；接真实 IAM 后改成解析其签发的 token。
    """
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-User-Id",
            headers={"WWW-Authenticate": "X-User-Id"},
        )
    return load_user(db, x_user_id)
