"""飞书开放平台 mock：httpx.MockTransport 实现，覆盖本单用到的三个接口。

不联网、不需要真实 app_id；可脚本化注入：授权码无效、凭证失效、权限不足、租户不匹配、超时、5xx。
"""

from __future__ import annotations

import httpx

APP_TOKEN_PATH = "/open-apis/auth/v3/app_access_token/internal"
USER_TOKEN_PATH = "/open-apis/authen/v1/oidc/access_token"
USER_INFO_PATH = "/open-apis/authen/v1/user_info"

CODE_OK = 0
CODE_INVALID_AUTH_CODE = 20003
CODE_CREDENTIAL_STALE = 99991663
CODE_NO_SCOPE = 99991672

# 哨兵值：测试用来断言"这些东西绝不能出现在日志里"
SENTINEL_SECRET = "SECRET-SENTINEL-7766"
SENTINEL_AUTH_CODE = "AUTHCODE-SENTINEL-9988"


class FeishuMock:
    """一个可编程的假飞书。

    属性：
        invalid_code          授权码无效（20003）
        insufficient_scope    应用权限不足（99991672）
        stale_user_token_times 前 N 次换码返回「应用访问凭证失效」（99991663）
        timeout_times         前 N 次请求抛超时
        server_error_times    前 N 次请求返回 500
        tenant_key            用户信息里返回的 tenant_key（可与配置不同以测租户校验）
    """

    def __init__(self, *, app_id: str, app_secret: str, tenant_key: str,
                 user_id: str = "ou_user_phys_id", open_id: str = "ou_openid_001",
                 union_id: str = "on_unionid_001", display_name: str = "虚构测试用户") -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.tenant_key = tenant_key
        self.user_id = user_id
        self.open_id = open_id
        self.union_id = union_id
        self.display_name = display_name

        self.invalid_code = False
        self.insufficient_scope = False
        self.stale_user_token_times = 0
        self.timeout_times = 0
        self.server_error_times = 0

        self.calls: list[dict] = []
        self._issued_app_tokens: list[str] = []
        self._issued_user_tokens: list[str] = []

    # ---- 统计 ----
    def count(self, path: str) -> int:
        return sum(1 for c in self.calls if c["path"] == path)

    @property
    def app_token_calls(self) -> int:
        return self.count(APP_TOKEN_PATH)

    @property
    def user_token_calls(self) -> int:
        return self.count(USER_TOKEN_PATH)

    @property
    def user_info_calls(self) -> int:
        return self.count(USER_INFO_PATH)

    # ---- HTTP ----
    def handler(self, request: httpx.Request) -> httpx.Response:
        body = {}
        if request.content:
            try:
                import json
                body = json.loads(request.content)
            except ValueError:
                body = {}
        self.calls.append({
            "method": request.method,
            "path": request.url.path,
            "headers": dict(request.headers),
            "body": body,
        })

        if self.timeout_times > 0:
            self.timeout_times -= 1
            raise httpx.ReadTimeout("mock timeout", request=request)
        if self.server_error_times > 0:
            self.server_error_times -= 1
            return httpx.Response(500, json={"code": 500, "msg": "internal"})

        path = request.url.path
        if path == APP_TOKEN_PATH:
            return self._app_token(body)
        if path == USER_TOKEN_PATH:
            return self._user_token(request)
        if path == USER_INFO_PATH:
            return self._user_info(request)
        return httpx.Response(404, json={"code": 404, "msg": "not found"})

    def _app_token(self, body: dict) -> httpx.Response:
        if body.get("app_id") != self.app_id or body.get("app_secret") != self.app_secret:
            return httpx.Response(200, json={"code": 10003, "msg": "invalid app credentials"})
        token = f"t-app-{len(self._issued_app_tokens) + 1}-mocked-sentinel"
        self._issued_app_tokens.append(token)
        return httpx.Response(200, json={"code": CODE_OK, "app_access_token": token, "expire": 7200})

    def _user_token(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        current = self._issued_app_tokens[-1] if self._issued_app_tokens else ""
        if not auth.endswith(current) or not current:
            return httpx.Response(200, json={"code": CODE_CREDENTIAL_STALE, "msg": "app token invalid"})
        if self.stale_user_token_times > 0:
            self.stale_user_token_times -= 1
            return httpx.Response(200, json={"code": CODE_CREDENTIAL_STALE, "msg": "app token invalid"})
        if self.invalid_code:
            return httpx.Response(200, json={"code": CODE_INVALID_AUTH_CODE, "msg": "code invalid"})
        if self.insufficient_scope:
            return httpx.Response(200, json={"code": CODE_NO_SCOPE, "msg": "no permission"})
        token = f"u-user-{len(self._issued_user_tokens) + 1}-mocked-sentinel"
        self._issued_user_tokens.append(token)
        return httpx.Response(200, json={
            "code": CODE_OK,
            "data": {"access_token": token, "expires_in": 7200, "token_type": "Bearer"},
        })

    def _user_info(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        current = self._issued_user_tokens[-1] if self._issued_user_tokens else ""
        if not current or not auth.endswith(current):
            return httpx.Response(200, json={"code": 20005, "msg": "user token invalid"})
        data = {
            "open_id": self.open_id,
            "union_id": self.union_id,
            "user_id": self.user_id,
            "tenant_key": self.tenant_key,
            "name": self.display_name,
        }
        if self.insufficient_scope:
            data.pop("user_id")
        return httpx.Response(200, json={"code": CODE_OK, "data": data})

    # ---- 出口 ----
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def client(self, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport(), **kwargs)
