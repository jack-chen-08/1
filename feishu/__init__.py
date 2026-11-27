"""飞书扫码登录适配器（S2-IAM-013）。

对外只暴露：配置、协议、提供方实现、缓存实现与错误码。
"""

from .config import ConfigError, FeishuConfig
from .errors import (
    PROVIDER_CREDENTIAL_EXPIRED,
    PROVIDER_INSUFFICIENT_SCOPE,
    PROVIDER_INVALID_CODE,
    PROVIDER_TENANT_MISMATCH,
    PROVIDER_TIMEOUT,
    PROVIDER_UNAVAILABLE,
    ProviderError,
)
from .protocols import LoginResult, QrLoginProvider
from .provider import FeishuProvider
from .token_cache import InMemoryTokenCache, RedisTokenCache, TokenCache, effective_ttl

__all__ = [
    "FeishuConfig", "ConfigError",
    "FeishuProvider", "QrLoginProvider", "LoginResult",
    "ProviderError",
    "PROVIDER_INVALID_CODE", "PROVIDER_CREDENTIAL_EXPIRED", "PROVIDER_INSUFFICIENT_SCOPE",
    "PROVIDER_TENANT_MISMATCH", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE",
    "TokenCache", "InMemoryTokenCache", "RedisTokenCache", "effective_ttl",
]
