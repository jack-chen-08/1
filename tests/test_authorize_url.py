"""授权链接：参数必须与飞书网页应用登录要求一致，且不泄露任何密钥。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from feishu import FeishuConfig, FeishuProvider, InMemoryTokenCache
from mock_feishu import SENTINEL_SECRET

APP_ID = "cli_test_app"
TENANT = "tenant_primary"
SECRET_ENV = "APP_FEISHU_APP_SECRET"


def make_provider() -> FeishuProvider:
    config = FeishuConfig.from_env({
        "APP_FEISHU_APP_ID": APP_ID,
        "APP_FEISHU_SECRET_NAME": SECRET_ENV,
        SECRET_ENV: SENTINEL_SECRET,
        "APP_FEISHU_TENANT_KEY": TENANT,
    })
    return FeishuProvider(config, InMemoryTokenCache())


def test_authorize_url_contains_required_params():
    provider = make_provider()
    url = provider.build_authorize_url(
        redirect_uri="https://app.example.com/api/auth/feishu/callback",
        state="state-abc123",
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "open.feishu.cn"
    assert parsed.path == "/open-apis/authen/v1/authorize"
    assert query["client_id"] == [APP_ID]              # client_id 即 app_id
    assert query["response_type"] == ["code"]
    assert query["state"] == ["state-abc123"]
    assert query["redirect_uri"] == ["https://app.example.com/api/auth/feishu/callback"]
    assert SENTINEL_SECRET not in url                  # 授权链接里绝不能出现密钥


def test_authorize_url_encodes_redirect_uri():
    provider = make_provider()
    url = provider.build_authorize_url(
        redirect_uri="https://app.example.com/cb?from=web&lang=zh",
        state="s-1",
    )
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fcb%3Ffrom%3Dweb%26lang%3Dzh" in url
