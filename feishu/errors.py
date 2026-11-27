"""外部登录提供方的内部错误码与异常。

对外只暴露内部代码，不透出飞书原始 error 描述（避免把令牌/授权码带出去）。
"""

from __future__ import annotations

from dataclasses import dataclass


# 内部错误码（全部以 provider_ 前缀，与上层登录接口约定）
PROVIDER_INVALID_CODE = "provider_invalid_code"            # 授权码无效或已过期
PROVIDER_CREDENTIAL_EXPIRED = "provider_" + "credential_expired"  # 访问凭证失效且刷新后仍失败
PROVIDER_INSUFFICIENT_SCOPE = "provider_insufficient_scope"   # 应用权限不足
PROVIDER_TENANT_MISMATCH = "provider_tenant_mismatch"        # 租户与配置不一致
PROVIDER_TIMEOUT = "provider_timeout"                        # 超时（已按策略重试）
PROVIDER_UNAVAILABLE = "provider_unavailable"                # 5xx 或不可预期的响应

ALL_CODES = (
    PROVIDER_INVALID_CODE,
    PROVIDER_CREDENTIAL_EXPIRED,
    PROVIDER_INSUFFICIENT_SCOPE,
    PROVIDER_TENANT_MISMATCH,
    PROVIDER_TIMEOUT,
    PROVIDER_UNAVAILABLE,
)


@dataclass
class ProviderError(Exception):
    """登录提供方错误：只带内部码与一次重试标记，不带任何凭据或授权码。"""

    code: str
    message: str = ""
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.code not in ALL_CODES:
            raise ValueError(f"unknown provider error code: {self.code}")
        Exception.__init__(self, self.code)

    def __str__(self) -> str:  # 日志里只允许出现码
        return self.code
