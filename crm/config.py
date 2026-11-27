"""配置：一律从环境变量读取，不在代码里写死任何密钥。

生产/联调用 PostgreSQL 16（pgvector），测试用同一套变量指向独立库。
DSN 由离散变量拼装（用户、口令、主机、端口、库名分开放），
因此任何单条配置都不含完整凭证串，便于按环境注入。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

DEFAULT_MATRIX = Path(__file__).parent / "permissions" / "matrix" / "opportunity.yaml"


def build_dsn() -> str:
    """按环境变量拼装 DSN；CRM_DATABASE_URL 优先。"""
    explicit = os.getenv("CRM_DATABASE_URL")
    if explicit:
        return explicit
    user = os.getenv("CRM_DB_USER", "crm")
    password = os.getenv("CRM_DB_PASSWORD", "")
    host = os.getenv("CRM_DB_HOST", "127.0.0.1")
    port = os.getenv("CRM_DB_PORT", "55432")
    name = os.getenv("CRM_DB_NAME", "crm")
    auth = f"{user}:{quote_plus(password)}@" if password else f"{user}@"
    return f"postgresql+psycopg://{auth}{host}:{port}/{name}"


class Settings:
    """轻量配置对象（只读）。"""

    def __init__(self) -> None:
        self.database_url: str = build_dsn()
        self.redis_url: str = os.getenv("CRM_REDIS_URL", "redis://127.0.0.1:6379/0")
        self.matrix_path: str = os.getenv("CRM_MATRIX_PATH", str(DEFAULT_MATRIX))
        self.sql_echo: bool = os.getenv("CRM_SQL_ECHO", "").lower() in {"1", "true", "yes"}


def get_settings() -> Settings:
    return Settings()
