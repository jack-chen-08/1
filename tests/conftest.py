"""测试夹具。

需要真实 PostgreSQL（pgvector + pg_trgm），因为本单的核心性质是
「过滤条件必须出现在 SQL 里」——用 SQLite 或假 session 测不出来。

环境变量（缺一不可）：KB_DB_USER / KB_DB_PASSWORD / KB_DB_HOST / KB_DB_PORT /
KB_TEST_DB_NAME。仓库根目录的 .env 会被自动读取（见 _load_env_if_present）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from kb.main import create_app
from kb.models import Base

ROOT = Path(__file__).resolve().parent.parent


def _load_env_if_present() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_if_present()


def _test_dsn() -> str:
    user = os.environ["KB_DB_USER"]
    password = os.environ["KB_DB_PASSWORD"]
    host = os.environ.get("KB_DB_HOST", "localhost")
    port = os.environ.get("KB_DB_PORT", "55433")
    name = os.environ["KB_TEST_DB_NAME"]
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(_test_dsn(), future=True, pool_pre_ping=True)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _clean_tables(engine):
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE kb_chunk, kb_document, app_user CASCADE"))


@pytest.fixture()
def client(engine):
    from kb.iam import get_session

    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[get_session] = _override
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
