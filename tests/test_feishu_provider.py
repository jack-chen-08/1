"""AC1 / AC2 / AC3 + 重试与缓存行为。全部走 httpx.MockTransport，不出网。"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from feishu import (
    PROVIDER_CREDENTIAL_EXPIRED,
    PROVIDER_INSUFFICIENT_SCOPE,
    PROVIDER_INVALID_CODE,
    PROVIDER_TENANT_MISMATCH,
    PROVIDER_TIMEOUT,
    PROVIDER_UNAVAILABLE,
    FeishuConfig,
    FeishuProvider,
    InMemoryTokenCache,
    ProviderError,
)
from mock_feishu import SENTINEL_AUTH_CODE, SENTINEL_SECRET, FeishuMock

pytestmark = pytest.mark.asyncio

APP_ID = "cli_test_app"
TENANT = "tenant_primary"
USER_ID = "user_8f3c1a"
SECRET_ENV = "APP" + "_FEISHU" + "_APP" + "_SECRET"



def new_mock(**overrides) -> FeishuMock:
    params = dict(app_id=APP_ID, app_secret=SENTINEL_SECRET, tenant_key=TENANT, user_id=USER_ID)
    params.update(overrides)
    return FeishuMock(**params)

def make_config() -> FeishuConfig:
    return FeishuConfig.from_env({
        "APP_FEISHU_APP_ID": APP_ID,
        "APP_FEISHU_SECRET_NAME": SECRET_ENV,
        SECRET_ENV: SENTINEL_SECRET,
        "APP_FEISHU_TENANT_KEY": TENANT,
    })


async def _no_sleep(_seconds: float) -> None:
    return None


def make_provider(mock: FeishuMock, cache=None) -> FeishuProvider:
    client = httpx.AsyncClient(transport=mock.transport(), timeout=5.0)
    return FeishuProvider(make_config(), cache or InMemoryTokenCache(),
                          http_client=client, sleep=_no_sleep)


# ---------- AC1 成功路径 ----------
async def test_success_returns_external_user_id_from_user_id():
    mock = new_mock()
    provider = make_provider(mock)

    result = await provider.exchange_code(code="auth-code-ok", redirect_uri="https://app.local/cb")

    assert result.external_user_id == USER_ID          # 外键取 user_id，不是 open_id
    assert result.open_id and result.union_id
    assert result.tenant_key == TENANT
    assert mock.app_token_calls == 1
    assert mock.user_token_calls == 1
    assert mock.user_info_calls == 1


async def test_app_token_is_cached_so_second_login_reuses_it():
    mock = new_mock()
    cache = InMemoryTokenCache()
    provider = make_provider(mock, cache)

    await provider.exchange_code(code="auth-code-1", redirect_uri="https://app.local/cb")
    await provider.exchange_code(code="auth-code-2", redirect_uri="https://app.local/cb")

    assert mock.app_token_calls == 1                   # 第二次命中缓存
    assert await cache.get(f"feishu:token:{APP_ID}")
    ttl = cache.ttl_of(f"feishu:token:{APP_ID}")
    assert 6500 < ttl <= 6900                          # 7200 提前 300 秒


# ---------- AC1 授权码无效 ----------
async def test_invalid_code_maps_to_provider_invalid_code_without_retry():
    mock = new_mock()
    mock.invalid_code = True
    provider = make_provider(mock)

    with pytest.raises(ProviderError) as exc:
        await provider.exchange_code(code="auth-code-bad", redirect_uri="https://app.local/cb")

    assert exc.value.code == PROVIDER_INVALID_CODE
    assert mock.user_token_calls == 1                  # 不刷新、不重试
    assert mock.app_token_calls == 1


# ---------- AC1 凭证失效自动重试 ----------
async def test_stale_credential_refreshes_token_and_retries_once():
    mock = new_mock()
    mock.stale_user_token_times = 1                    # 第一次换码返回凭证类错误码
    provider = make_provider(mock)

    result = await provider.exchange_code(code="auth-code-ok", redirect_uri="https://app.local/cb")

    assert result.external_user_id == USER_ID
    assert mock.app_token_calls == 2                   # 首次取 + 强制刷新
    assert mock.user_token_calls == 2                  # 失败一次 + 重试一次


async def test_stale_credential_retries_only_once():
    mock = new_mock()
    mock.stale_user_token_times = 9                    # 一直失效
    provider = make_provider(mock)

    with pytest.raises(ProviderError) as exc:
        await provider.exchange_code(code="auth-code-ok", redirect_uri="https://app.local/cb")

    assert exc.value.code == PROVIDER_CREDENTIAL_EXPIRED
    assert mock.user_token_calls == 2


# ---------- AC1 / AC2 租户不匹配 ----------
async def test_tenant_mismatch_returns_provider_tenant_mismatch():
    mock = new_mock(tenant_key="tenant_other_company")
    provider = make_provider(mock)

    with pytest.raises(ProviderError) as exc:
        await provider.exchange_code(code="auth-code-ok", redirect_uri="https://app.local/cb")

    assert exc.value.code == PROVIDER_TENANT_MISMATCH == "provider_tenant_mismatch"


async def test_insufficient_scope_when_user_id_missing():
    mock = new_mock()
    mock.insufficient_scope = True                     # user_info 不返回 user_id
    provider = make_provider(mock)

    with pytest.raises(ProviderError) as exc:
        await provider.exchange_code(code="auth-code-ok", redirect_uri="https://app.local/cb")

    assert exc.value.code == PROVIDER_INSUFFICIENT_SCOPE


# ---------- AC3 日志里不能出现 token / secret / 授权码 ----------
async def test_logs_contain_no_token_secret_or_auth_code(caplog):
    mock = new_mock(tenant_key="tenant_other_company")
    provider = make_provider(mock)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ProviderError):
            await provider.exchange_code(code=SENTINEL_AUTH_CODE, redirect_uri="https://app.local/cb")

    text = caplog.text
    assert SENTINEL_SECRET not in text
    assert SENTINEL_AUTH_CODE not in text
    assert "mocked-sentinel" not in text               # 应用凭证 / 用户凭证
    assert "Bearer " not in text
    assert PROVIDER_TENANT_MISMATCH in text            # 关键码仍可定位


# ---------- 重试策略：超时 / 5xx 最多 2 次 ----------
async def test_timeout_retries_twice_then_succeeds():
    mock = new_mock()
    mock.timeout_times = 2
    provider = make_provider(mock)

    result = await provider.exchange_code(code="auth-code-ok", redirect_uri="https://app.local/cb")
    assert result.external_user_id == USER_ID
    assert mock.app_token_calls == 3                   # 1 + 2 次重试


async def test_timeout_exhausted_maps_to_provider_timeout():
    mock = new_mock()
    mock.timeout_times = 9
    provider = make_provider(mock)

    with pytest.raises(ProviderError) as exc:
        await provider.exchange_code(code="auth-code-ok", redirect_uri="https://app.local/cb")
    assert exc.value.code == PROVIDER_TIMEOUT
    assert mock.app_token_calls == 3


async def test_5xx_retries_then_fails_as_unavailable():
    mock = new_mock()
    mock.server_error_times = 9
    provider = make_provider(mock)

    with pytest.raises(ProviderError) as exc:
        await provider.exchange_code(code="auth-code-ok", redirect_uri="https://app.local/cb")
    assert exc.value.code == PROVIDER_UNAVAILABLE
    assert mock.app_token_calls == 3


# ---------- 并发：冷缓存下只刷新一次 ----------
async def test_concurrent_logins_share_one_refresh():
    mock = new_mock()
    provider = make_provider(mock)

    results = await asyncio.gather(*[
        provider.exchange_code(code=f"auth-code-{i}", redirect_uri="https://app.local/cb")
        for i in range(5)
    ])
    assert all(r.external_user_id == USER_ID for r in results)
    assert mock.app_token_calls == 1
