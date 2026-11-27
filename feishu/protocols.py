"""登录提供方协议与结果对象。

上层（账号体系/登录接口工单）只依赖本协议，不依赖飞书细节：
    url = provider.build_authorize_url(redirect_uri=..., state=...)
    result = await provider.exchange_code(code=..., redirect_uri=..., state=...)
    result.external_user_id  # 落库的唯一外键，本实现为飞书 user_id
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LoginResult:
    """一次成功登录的最小结果集；不含任何令牌。"""

    provider: str
    external_user_id: str      # 企业内唯一（飞书 user_id），作为账号体系外键
    open_id: str
    union_id: str
    tenant_key: str
    display_name: str = ""


@runtime_checkable
class QrLoginProvider(Protocol):
    """扫码登录提供方协议（飞书 / 微信 / 钉钉 均按此实现）。"""

    name: str

    def build_authorize_url(self, *, redirect_uri: str, state: str) -> str:
        ...

    async def exchange_code(self, *, code: str, redirect_uri: str, state: str | None = None) -> LoginResult:
        ...
