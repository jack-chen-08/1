"""SQLAlchemy 2.0 engine / session。

故意做惰性初始化：导入本模块不应触发任何数据库连接，
便于只读场景（如矩阵测试）在没有数据库时也能跑。
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kb.config import Settings, load_settings

_engine = None
_session_factory = None


def get_engine(settings: Settings | None = None, override_url: str | None = None):
    global _engine
    if override_url is not None:
        return create_engine(override_url, future=True, pool_pre_ping=True)
    if _engine is None:
        s = settings or load_settings()
        _engine = create_engine(s.dsn, future=True, pool_pre_ping=True)
    return _engine


def get_session_factory(engine=None) -> sessionmaker:
    global _session_factory
    if engine is not None:
        return sessionmaker(bind=engine, expire_on_commit=False, future=True)
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), expire_on_commit=False, future=True
        )
    return _session_factory


def new_session() -> Session:
    return get_session_factory()()


@contextmanager
def session_scope():
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
