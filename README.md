# 飞书扫码登录适配器（S2-IAM-013）

按 `QrLoginProvider` 协议实现 `FeishuProvider`：生成授权链接、用授权码换取用户身份、并做租户校验。上层账号体系只依赖协议，不依赖飞书细节。

技术栈：Python 3.11+ / httpx / redis.asyncio / pytest（全部单测走 `httpx.MockTransport`，不联网、不需要真实应用）。

## 1. 目录

```
feishu/
  protocols.py     QrLoginProvider 协议 + LoginResult
  provider.py      FeishuProvider：授权链接 / 换码 / 用户信息 / 错误码映射 / 重试
  config.py        环境变量配置（密钥间接寻址，repr 脱敏）
  token_cache.py   应用访问凭证缓存（Redis / 内存两种实现）+ 刷新锁 + TTL 提前量
  redaction.py     日志脱敏兜底过滤器
  errors.py        内部错误码与 ProviderError
mock_feishu.py     可编程的假飞书（MockTransport）
tests/             AC1–AC4 的用例
```

## 2. 运行与测试

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q            # 或 bash run_tests.sh
```

生产环境额外需要 `redis>=5`（`RedisTokenCache`）与真实飞书应用配置；测试用 `InMemoryTokenCache`，不依赖 Redis。

## 3. 飞书开放平台配置（上线前必做）

### 3.1 重定向 URL

在「飞书开放平台 → 应用 → 安全设置 → 重定向 URL」添加：

```
https://<你的域名>/api/auth/feishu/callback
```

`redirect_uri` 必须与后台登记值逐字节一致（含协议、端口、末尾斜杠），否则飞书会拒绝授权并返回错误码。多环境（测试/预发/生产）各自登记一条。

### 3.2 需要开通的权限

| 权限 | 用途 |
|---|---|
| `contact:user.base:readonly` | 获取用户基本信息：`open_id`、`union_id`、`name` |
| `contact:user.employee_id:readonly` | 获取用户 `user_id`（企业内唯一，本适配器用它作 external_user_id） |

未开通 `contact:user.employee_id:readonly` 时 `user_info` 不返回 `user_id`，适配器会返回 `provider_insufficient_scope`。

### 3.3 环境变量

| 变量 | 说明 |
|---|---|
| `APP_FEISHU_APP_ID` | 应用 app_id |
| `APP_FEISHU_SECRET_NAME` | **存放 app_secret 的环境变量名**（例如 `APP_FEISHU_APP_SECRET`），密钥本身只存在于运行环境 |
| `APP_FEISHU_TENANT_KEY` | 本企业租户标识，用于拒绝其他企业账号登录 |

可选：`FEISHU_BASE_URL`（默认 `https://open.feishu.cn`，私有化/代理时改这里）。

## 4. 对接点

```python
from feishu import FeishuConfig, FeishuProvider, RedisTokenCache

config = FeishuConfig.from_env()                 # 只从环境变量读
provider = FeishuProvider(config, RedisTokenCache(redis_client))

url = provider.build_authorize_url(redirect_uri=REDIRECT_URI, state=csrf_state)
result = await provider.exchange_code(code=code, redirect_uri=REDIRECT_URI, state=csrf_state)
# result.external_user_id → 账号体系外键；result.tenant_key → 审计用
```

- 回调接口（`/api/auth/feishu/callback`）由登录接口工单实现，本单只提供适配器与协议。
- 上层需要把 `ProviderError.code` 映射为 HTTP 响应；本适配器的码表见第 5.3 节。
- `state` 由调用方生成并校验（CSRF），适配器只透传，不存储。

## 5. 设计要点

### 5.1 为什么 external_user_id 用 user_id 而不是 open_id

`open_id` 是「用户 × 应用」维度的标识：同一员工在同一企业下不同应用里的 `open_id` 不同；一旦更换应用（或重建应用），`open_id` 会变，历史账号就绑不上。
`user_id` 是企业在飞书通讯录里的员工唯一标识，跨应用稳定，因此作为 external_user_id 落库。`union_id` 也随返回结果保存，供未来跨应用/跨企业合流使用。

### 5.2 应用访问凭证：缓存 + 提前过期 + 刷新锁

- 缓存键 `feishu:token:{app_id}`；
- TTL 取 `expire - 300` 秒（提前 5 分钟），过小时保底 30 秒，避免出现「缓存永不命中」；
- 刷新时取 Redis 锁 `feishu:token:lock:{app_id}`，锁内**双检缓存**，防止并发刷新打爆飞书接口；
- 拿不到锁时不阻塞业务：再读一次缓存，仍为空则自行请求（最多多打一次飞书）。

### 5.3 错误码映射

| 场景 | 内部码 | 是否重试 |
|---|---|---|
| 授权码无效 / 过期 | `provider_invalid_code` | 否 |
| 访问凭证失效（飞书凭证类错误码） | 自动刷新应用凭证后重试 1 次；仍失败 `provider_credential_expired` | 是（1 次） |
| 权限不足（含 `user_id` 缺失） | `provider_insufficient_scope` | 否 |
| `tenant_key` 与配置不一致 | `provider_tenant_mismatch` | 否 |
| 超时（单请求 5 秒） | `provider_timeout`（已重试 2 次） | 是（≤2 次） |
| 5xx / 非预期响应 | `provider_unavailable` | 是（≤2 次） |

对外只返回内部码，不透出飞书原始文案，避免把授权码、令牌带进响应或日志。

### 5.4 日志

- 只记录事件名、内部码与 `app_id`；不记录授权码、app_secret、app_access_token、user_access_token。
- `redaction.RedactionFilter` 作为兜底：`t-/u-/a-` 前缀长串、`Bearer ...`、注册过的密钥值统一替换为 `***`。
- 有专门用例 `test_logs_contain_no_token_secret_or_auth_code` 在 DEBUG 级别抓日志并断言哨兵值不出现。

## 6. 验证

```bash
bash run_tests.sh     # pytest + README 契约检查
```

四条验收对应的用例：

| 验收 | 用例 |
|---|---|
| 成功路径 | `test_success_returns_external_user_id_from_user_id` |
| 授权码无效 | `test_invalid_code_maps_to_provider_invalid_code_without_retry` |
| 凭证失效自动重试 | `test_stale_credential_refreshes_token_and_retries_once` |
| 租户不匹配 | `test_tenant_mismatch_returns_provider_tenant_mismatch` |
| 日志无敏感值 | `test_logs_contain_no_token_secret_or_auth_code` |
| README 配置齐全 | `test_readme_documents_console_setup` |

## 7. 已知边界

- 本单不实现登录会话、Cookie/JWT 签发与账号落库（属登录接口与账号体系工单）；适配器只负责「拿到可信的外部身份」。
- 不处理飞书事件订阅（通讯录变更、离职同步）——属 S2-IAM 其他工单。
- `tenant_key` 校验只做等值比较；如需支持多租户白名单，在配置层扩展为集合。
- 私有化部署时 `FEISHU_BASE_URL` 指向内网网关，证书与域名由 S2-INFRA 提供。
