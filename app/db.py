"""数据库与运行配置。

约定：
- 生产：PostgreSQL 16 + asyncpg，DSN 只从环境变量读取。
- 本地/测试：sqlite+aiosqlite，便于零依赖复跑。
- 所有表统一带 id / org_id / site_id / created_at / created_by / updated_at / deleted_at。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """统一时间列：入库存 naive UTC（兼容 SQLite），出库还原为带时区的 UTC。"""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./academy_dev.db")
    activity_base_url: str = os.getenv("ACTIVITY_BASE_URL", "http://127.0.0.1:8099")
    activity_token: str = os.getenv("ACTIVITY_TOKEN", "")
    retry_max_attempts: int = int(os.getenv("RETRY_MAX_ATTEMPTS", "5"))
    retry_base_seconds: int = int(os.getenv("RETRY_BASE_SECONDS", "30"))


settings = Settings()


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None, echo: bool = False):
    return create_async_engine(url or settings.database_url, echo=echo, future=True)


def make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine) -> None:
    from . import models  # noqa: F401  确保元数据已注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
