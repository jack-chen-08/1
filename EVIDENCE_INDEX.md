# EVIDENCE_INDEX — S2-IAM-013 飞书扫码登录适配器

取证索引：每条验收 → 判据 → 代码位置 → 复跑命令 → 本轮实测数字。
所有数字来自 2026-11-27 本机实跑（Python 3.12.13 / pytest 9.1.1 / httpx 0.28），全部为虚构数据，未联网。

## 0. 一句话结论

`bash run_tests.sh` → **21 passed in 1.36s**；四条验收路径（成功 / 授权码无效 / 凭证失效自动重试 / 租户不匹配）各有独立用例，另有日志脱敏、重试上限、缓存与锁、授权链接参数、README 配置契约共 21 条。

## 1. 文件与指纹

| 文件 | 行数 | sha256 前 16 |
|---|---|---|
| `feishu/provider.py` | 244 | `b69fd87ec5d7c95b` |
| `feishu/token_cache.py` | 120 | `1717895c9b0acdf3` |
| `feishu/config.py` | 57 | `c3322948875ca128` |
| `feishu/errors.py` | 43 | `3768775636867f77` |
| `feishu/protocols.py` | 37 | `4fb0b6f401f0327e` |
| `feishu/redaction.py` | 36 | `89fcc55861df16c6` |
| `mock_feishu.py` | 152 | `3f1eef70bad3e4bf` |
| `tests/test_feishu_provider.py` | 208 | `3215af041548cc82` |
| `tests/test_token_cache.py` | 120 | `98467377db45db8b` |
| `tests/test_authorize_url.py` | 50 | `12cdd4827e2e4cea` |
| `tests/test_readme_contract.py` | 31 | `79f636c18e8bbb8e` |
| `README.md` | 134 | `efa6f4e05412d547` |

Python 合计 1125 行（不含 README 与配置文件）。

## 2. 验收逐条

### AC1 四种路径 mock 测试通过

| 路径 | 用例 | 关键断言 | 实测 |
|---|---|---|---|
| 成功 | `test_success_returns_external_user_id_from_user_id` | `external_user_id == user_id`；三接口各调 1 次 | passed |
| 授权码无效 | `test_invalid_code_maps_to_provider_invalid_code_without_retry` | `code == provider_invalid_code`；换码只调 1 次，不刷新应用凭证 | passed |
| 凭证失效自动重试 | `test_stale_credential_refreshes_token_and_retries_once` | 应用凭证 2 次（首次 + 刷新）、换码 2 次（失败 + 重试） | passed |
| 凭证失效重试上限 | `test_stale_credential_retries_only_once` | 仍失败 → `provider_credential_expired`，换码恰好 2 次 | passed |
| 租户不匹配 | `test_tenant_mismatch_returns_provider_tenant_mismatch` | `code == "provider_tenant_mismatch"` | passed |

### AC2 tenant_key 不一致返回 provider_tenant_mismatch

用例 `test_tenant_mismatch_returns_provider_tenant_mismatch` 直接断言字面量：
`assert exc.value.code == PROVIDER_TENANT_MISMATCH == "provider_tenant_mismatch"`。
校验点在 `feishu/provider.py` 的 `exchange_code`：拿到 `user_info` 后立即比较 `tenant_key`，不等值即抛错，不会签发任何本地会话。

### AC3 测试日志里搜不到 token / secret / 授权码

用例 `test_logs_contain_no_token_secret_or_auth_code`：DEBUG 级别捕获 `feishu.provider` 日志，断言
- 哨兵密钥 `SECRET-SENTINEL-7766` 不出现；
- 哨兵授权码 `AUTHCODE-SENTINEL-9988` 不出现；
- mock 签发的应用凭证与用户凭证（含 `mocked-sentinel` 标记）不出现；
- `Bearer ` 不出现；
- 同时断言 `provider_tenant_mismatch` 仍可出现（证明不是"把日志全关掉"过关）。

两道保险：`provider.py` 只记录事件名与内部码；`feishu/redaction.py` 的 `RedactionFilter` 兜底把 `t-/u-/a-` 长串、`Bearer ...`、注册密钥替换为 `***`。

### AC4 README 列出后台权限与重定向 URL

用例 `test_readme_documents_console_setup` 断言 README 含：`/api/auth/feishu/callback` 重定向 URL、`contact:user.base:readonly`、`contact:user.employee_id:readonly`、三个环境变量名、以及 open_id/user_id 取舍说明。

## 3. 复跑命令

```bash
cd <repo>
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
bash run_tests.sh
# 期望：21 passed
```

不需要 Redis、不需要真实飞书应用、不需要外网。Redis 实现由 `tests/test_token_cache.py` 的 `FakeRedis` 覆盖读写、TTL 提前量、锁释放。

## 4. 口径说明（容易被误判的地方）

1. **应用凭证的 TTL 提前 5 分钟**：`effective_ttl(7200, 300) == 6900`，并断言 Redis `set(..., ex=6900)`，不是裸用飞书给的 `expire`。
2. **刷新锁内双检**：并发 5 个登录只产生 1 次应用凭证请求（`test_concurrent_logins_share_one_refresh`），证明锁有效而非仅"加了锁对象"。
3. **重试边界**：超时/5xx 最多重试 2 次（总 3 次请求），用 `test_timeout_exhausted_maps_to_provider_timeout` 断言恰好 3 次；授权码无效、租户不匹配、权限不足一律不重试。
4. **external_user_id 用 user_id**：`open_id` 是「用户 × 应用」维度，换应用即变；`user_id` 跨应用稳定。README 5.1 节有完整理由。
5. **租户校验发生在换码之后、签发之前**：不通过就不落任何本地会话，避免"先建号再回滚"。
6. **不落任何令牌**：`LoginResult` 只带身份字段，不含 access_token；令牌只在内存中传递。

## 5. 边界

- 不实现本地会话/JWT 签发与账号落库（登录接口与账号体系工单）。
- 不实现飞书通讯录事件订阅（S2-IAM 其他工单）。
- 私有化部署通过 `FEISHU_BASE_URL` 指向内网网关，证书由 S2-INFRA 提供。
