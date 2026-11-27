"""FeishuProvider：飞书网页应用扫码登录适配器。

流程（对应需求「本单范围」）：
1. build_authorize_url  组装授权页链接（client_id=app_id、redirect_uri、state、response_type=code）
2. exchange_code
   a. 取应用访问凭证：Redis 缓存 `feishu:token:{app_id}`，按 expire 提前 5 分钟过期，刷新时加锁
   b. 用授权码换 user_access_token
   c. 用 user_access_token 取用户信息（open_id / union_id / user_id / tenant_key）
   d. tenant_key 必须等于配置值，否则 provider_tenant_mismatch
   e. external_user_id 统一取 user_id（企业内唯一；open_id 跨应用不唯一，README 有说明）

重试策略：超时与 5xx 最多重试 2 次；凭证失效（飞书返回凭证类错误码）刷新一次后重试 1 次；
授权码无效、权限不足、租户不匹配一律不重试。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import FeishuConfig
from .errors import (
    PROVIDER_CREDENTIAL_EXPIRED,
    PROVIDER_INSUFFICIENT_SCOPE,
    PROVIDER_INVALID_CODE,
    PROVIDER_TENANT_MISMATCH,
    PROVIDER_TIMEOUT,
    PROVIDER_UNAVAILABLE,
    ProviderError,
)
from .protocols import LoginResult
from .redaction import RedactionFilter
from .token_cache import TokenCache, effective_ttl, lock_key, token_key

LOG = logging.getLogger("feishu.provider")
LOG.addFilter(RedactionFilter())

FEISHU_OK = 0
MAX_RETRIES = 2                      # 仅超时 / 5xx 生效，另有一次凭证刷新重试

# 飞书错误码归组（只依赖分组，不依赖具体文案）
CODES_INVALID = frozenset({20003, 20004, 20009, 20010, 20012, 20029, 20050})
CODES_CREDENTIAL_STALE = frozenset({99991661, 99991663, 99991668, 20005, 20026})
CODES_SCOPE = frozenset({99991672, 41050, 20027})

AUTHORIZE_PATH = "/open-apis/authen/v1/authorize"
APP_TOKEN_PATH = "/open-apis/auth/v3/app_access_token/internal"
USER_TOKEN_PATH = "/open-apis/authen/v1/oidc/access_token"
USER_INFO_PATH = "/open-apis/authen/v1/user_info"


class FeishuProvider:
    name = "feishu"

    def __init__(
        self,
        config: FeishuConfig,
        cache: TokenCache,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep=None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.config = config
        self.cache = cache
        self._client = http_client
        self._owns_client = http_client is None
        self._sleep = sleep or asyncio.sleep
        self._timeout = timeout_seconds if timeout_seconds is not None else config.timeout_seconds
        LOG.addFilter(RedactionFilter((config.secret,)))

    # ---------- 1. 授权链接 ----------
    def build_authorize_url(self, *, redirect_uri: str, state: str) -> str:
        query = urlencode({
            "client_id": self.config.app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        })
        return f"{self.config.base_url}{AUTHORIZE_PATH}?{query}"

    # ---------- 2. 换码 ----------
    async def exchange_code(self, *, code: str, redirect_uri: str, state: str | None = None) -> LoginResult:
        LOG.info("feishu.exchange_code start app_id=%s has_state=%s", self.config.app_id, bool(state))
        app_token = await self._app_access_token()

        try:
            token_payload = await self._exchange_user_token(app_token, code)
        except ProviderError as exc:
            if exc.code != PROVIDER_CREDENTIAL_EXPIRED:
                LOG.warning("feishu.exchange_code failed code=%s", exc.code)
                raise
            # 访问凭证失效：清缓存 + 强制刷新，重试 1 次
            LOG.info("feishu.app_token_refresh reason=user_token_rejected")
            await self.cache.delete(token_key(self.config.app_id))
            app_token = await self._app_access_token(force=True)
            token_payload = await self._exchange_user_token(app_token, code)

        user_token = token_payload.get("access_token") or ""
        if not user_token:
            raise ProviderError(PROVIDER_UNAVAILABLE, "no user access token in response")

        profile = await self._user_info(user_token)
        tenant_key = str(profile.get("tenant_key") or "")
        if tenant_key != self.config.tenant_key:
            LOG.warning("feishu.exchange_code tenant_mismatch code=%s", PROVIDER_TENANT_MISMATCH)
            raise ProviderError(PROVIDER_TENANT_MISMATCH)

        user_id = str(profile.get("user_id") or "")
        if not user_id:
            # user_id 需要开通「获取用户 user ID」权限
            LOG.warning("feishu.exchange_code missing_user_id")
            raise ProviderError(PROVIDER_INSUFFICIENT_SCOPE, "user_id missing (permission?)")

        LOG.info("feishu.exchange_code ok")
        return LoginResult(
            provider=self.name,
            external_user_id=user_id,
            open_id=str(profile.get("open_id") or ""),
            union_id=str(profile.get("union_id") or ""),
            tenant_key=tenant_key,
            display_name=str(profile.get("name") or ""),
        )

    # ---------- 内部：应用访问凭证 ----------
    async def _app_access_token(self, force: bool = False) -> str:
        key = token_key(self.config.app_id)
        if not force:
            cached = await self.cache.get(key)
            if cached:
                LOG.info("feishu.app_token cache_hit")
                return cached

        async with self.cache.lock(lock_key(self.config.app_id)) as acquired:
            if acquired:
                if not force:
                    cached = await self.cache.get(key)      # 双检：等锁期间可能已被别的协程刷新
                    if cached:
                        return cached
                return await self._fetch_app_token()
            # 未拿到锁：不阻塞业务，直接再读一次缓存，仍无则自行请求
            LOG.info("feishu.app_token lock_busy")
            cached = await self.cache.get(key)
            return cached or await self._fetch_app_token()

    async def _fetch_app_token(self) -> str:
        data = await self._request(
            "POST", APP_TOKEN_PATH,
            body={"app_id": self.config.app_id, "app_secret": self.config.secret},
        )
        self._raise_for_code(data)
        token = str(data.get("app_access_token") or data.get("tenant_access_token") or "")
        if not token:
            raise ProviderError(PROVIDER_UNAVAILABLE, "no app access token in response")
        expire = int(data.get("expire") or data.get("expires_in") or 7200)
        ttl = effective_ttl(expire, self.config.cache_ttl_skew_seconds)
        await self.cache.set(token_key(self.config.app_id), token, ttl)
        LOG.info("feishu.app_token refreshed ttl=%s", ttl)
        return token

    async def _exchange_user_token(self, app_token: str, code: str) -> dict[str, Any]:
        data = await self._request(
            "POST", USER_TOKEN_PATH,
            headers={"Authorization": f"Bearer {app_token}"},
            body={"grant_type": "authorization_code", "code": code},
        )
        self._raise_for_code(data)
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        return payload

    async def _user_info(self, user_token: str) -> dict[str, Any]:
        data = await self._request(
            "GET", USER_INFO_PATH,
            headers={"Authorization": f"Bearer {user_token}"},
        )
        self._raise_for_code(data)
        return data.get("data") if isinstance(data.get("data"), dict) else {}

    # ---------- 内部：错误码映射 ----------
    def _raise_for_code(self, data: dict[str, Any]) -> None:
        code = int(data.get("code", FEISHU_OK) or FEISHU_OK)
        if code == FEISHU_OK:
            return
        if code in CODES_INVALID:
            raise ProviderError(PROVIDER_INVALID_CODE, f"feishu code {code}")
        if code in CODES_CREDENTIAL_STALE:
            raise ProviderError(PROVIDER_CREDENTIAL_EXPIRED, f"feishu code {code}", retryable=True)
        if code in CODES_SCOPE:
            raise ProviderError(PROVIDER_INSUFFICIENT_SCOPE, f"feishu code {code}")
        raise ProviderError(PROVIDER_UNAVAILABLE, f"feishu code {code}")

    # ---------- 内部：传输层（超时 / 5xx 重试） ----------
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, *, headers=None, body=None) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        last_status: int | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._http().request(
                    method, url, headers=headers, json=body, timeout=self._timeout,
                )
            except httpx.TimeoutException:
                last_status = None
                if attempt < MAX_RETRIES:
                    LOG.info("feishu.request timeout retry attempt=%s path=%s", attempt + 1, path)
                    await self._sleep(0.2 * (2 ** attempt))
                    continue
                raise ProviderError(PROVIDER_TIMEOUT, "feishu request timed out")
            except httpx.HTTPError:
                raise ProviderError(PROVIDER_UNAVAILABLE, "feishu transport error")

            if response.status_code >= 500:
                last_status = response.status_code
                if attempt < MAX_RETRIES:
                    LOG.info("feishu.request 5xx retry attempt=%s status=%s", attempt + 1, response.status_code)
                    await self._sleep(0.2 * (2 ** attempt))
                    continue
                raise ProviderError(PROVIDER_UNAVAILABLE, f"feishu 5xx {response.status_code}")

            if response.status_code >= 400:
                raise ProviderError(PROVIDER_UNAVAILABLE, f"feishu http {response.status_code}")

            try:
                data = response.json()
            except ValueError:
                raise ProviderError(PROVIDER_UNAVAILABLE, "feishu non-json response")
            if not isinstance(data, dict):
                raise ProviderError(PROVIDER_UNAVAILABLE, "feishu unexpected payload")
            return data

        raise ProviderError(PROVIDER_UNAVAILABLE, f"feishu exhausted retries {last_status}")
