"""配置：只从离散环境变量读取。

约定：任何单条环境变量都不含完整凭证串，DSN 由离散字段在运行时拼装。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"缺少必填环境变量：{name}")
    return value


def _optional(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    db_user: str
    db_password: str
    db_host: str
    db_port: str
    db_name: str
    matrix_path: Path

    @property
    def dsn(self) -> str:
        """运行期拼装，不在任何单一配置项里出现完整凭证串。"""
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


def load_settings(db_name: str | None = None) -> Settings:
    default_matrix = Path(__file__).parent / "policy" / "visibility_matrix.yaml"
    return Settings(
        db_user=_required("KB_DB_USER"),
        db_password=_required("KB_DB_PASSWORD"),
        db_host=_optional("KB_DB_HOST", "localhost"),
        db_port=_optional("KB_DB_PORT", "55433"),
        db_name=db_name or _required("KB_DB_NAME"),
        matrix_path=Path(_optional("KB_MATRIX_PATH", str(default_matrix))),
    )
