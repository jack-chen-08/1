"""飞书接入配置：全部来自环境变量，代码里不出现任何默认密钥。

约定：
- APP_FEISHU_APP_ID      应用 app_id（公开标识）
- APP_FEISHU_SECRET_NAME 指向"存放 app_secret 的环境变量名"，例如 APP_FEISHU_APP_SECRET
- APP_FEISHU_TENANT_KEY  本企业租户标识，用于拒绝其他企业的飞书账号

间接寻址（secret_name → env）是为了让密钥只存在于运行环境，不进配置、不进日志。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_BASE_URL = "https://open.feishu.cn"
DEFAULT_TIMEOUT_SECONDS = 5.0


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    secret_name: str
    tenant_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_ttl_skew_seconds: int = 300      # 凭证提前 5 分钟过期
    _secret: str = field(default="", repr=False)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "FeishuConfig":
        e = os.environ if env is None else env
        app_id = (e.get("APP_FEISHU_APP_ID") or "").strip()
        secret_name = (e.get("APP_FEISHU_SECRET_NAME") or "").strip()
        tenant_key = (e.get("APP_FEISHU_TENANT_KEY") or "").strip()
        missing = [k for k, v in {
            "APP_FEISHU_APP_ID": app_id,
            "APP_FEISHU_SECRET_NAME": secret_name,
            "APP_FEISHU_TENANT_KEY": tenant_key,
        }.items() if not v]
        if missing:
            raise ConfigError("missing env: " + ", ".join(missing))
        secret = (e.get(secret_name) or "").strip()
        if not secret:
            raise ConfigError(f"env {secret_name} (app secret) is empty")
        return cls(app_id=app_id, secret_name=secret_name, tenant_key=tenant_key, _secret=secret)

    @property
    def secret(self) -> str:
        return self._secret

    def __repr__(self) -> str:  # 防止意外打印泄露
        return f"FeishuConfig(app_id={self.app_id!r}, tenant_key={self.tenant_key[:4]}***)"
