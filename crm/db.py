"""数据库会话与模型基类（SQLAlchemy 2.0 风格）。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from crm.config import get_settings


class Base(DeclarativeBase):
    """全部业务表的基类。"""


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    """惰性建 engine —— 测试可先设环境变量再首次调用。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=settings.sql_echo,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def reset_engine() -> None:
    """测试用：丢弃已缓存的 engine 与 sessionmaker。"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False
        )
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每请求一个会话。"""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """脚本/测试用事务上下文。"""
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
