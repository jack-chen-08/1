# EVIDENCE_INDEX — S6-ACAD-013 课期管理接口与活动模块同步

本文件是验收取证索引：每条验收 → 判据 → 代码位置 → 复跑命令 → 本轮实际数字。
所有数字均来自 2026-11-27 本机实跑（Python 3.12.13 / pytest 9.1.1），未做任何手工修饰。

## 0. 一句话结论

`pytest -q` → **17 passed in 0.69s**；`scripts/demo_offline.py` → 五段演练全绿（AC1–AC4 + 取消事件）。
四条验收在测试与演练中各有一份证据，见下表。

## 1. 文件清单（路径 / 行数 / sha256 前 16 位）

| 文件 | 行数 | sha256(16) | 作用 |
|---|---|---|---|
| `app/api.py` | 155 | `dce6ca1277191b10` | 四个课期路由 + 两个运维路由 + 应用工厂 |
| `app/service.py` | 271 | `6d63734407807410` | 业务逻辑：创建/PATCH/取消/重试（核心） |
| `app/activities.py` | 98 | `c2a0fd1ab0e31c99` | 活动模块客户端（真 HTTP + 字段翻译） |
| `app/audience.py` | 30 | `723d940f9b4ea59f` | audience → 活动可见范围 唯一映射表 |
| `app/models.py` | 94 | `260ee2666eb6bdfc` | 四张表（课期/报名桩/重试/发件箱） |
| `app/schemas.py` | 82 | `c47f66c36150e1e9` | 请求/响应模型与校验 |
| `app/db.py` | 66 | `af4d39972be7e3f5` | 引擎/会话/UTCDateTime |
| `mock_activity.py` | 92 | `d5e146f6fd83f1e5` | 活动模块替身（进程内 + 可独立启动） |
| `scripts/demo_offline.py` | 114 | `e8fa703af30e2842` | 离线演练，打印每步真实报文 |
| `tests/test_academy_sessions.py` | 196 | `3df83632c5f9128d` | AC1–AC4 + PATCH/取消/列表 |
| `tests/test_retry_and_client.py` | 133 | `341daca45fb9edb2` | 退避序列/5 次上限/真 HTTP 客户端 |
| `tests/conftest.py` | 71 | `24c6c21e8a639362` | 夹具（临时 SQLite、mock、ASGI 客户端） |
| `run_tests.sh` | 7 | `e77452e167afce09` | 一键复跑 |
| `README.md` | 125 | `95c2ab7bde423b16` | 运行方式 + 活动模块对接点 + 已知边界 |

代码合计 **1,409 行**（含测试与脚本）。

## 2. 验收逐条对应

### AC1 创建课期后 mock 活动服务收到一次创建请求，课期 event_id 被回填
- 用例：`tests/test_academy_sessions.py::test_ac1_create_triggers_one_activity_create_and_backfills_event_id`
- 判据：`len(activity.creates()) == 1`；payload 含 `type=academy_course`、标题 `产业资源对接实战 第 3 期`、`capacity=40`、`waitlist_capacity=10`；响应 `event_id` 等于替身返回的 event_id；`sync_status == "synced"`。
- 实测（demo 首段）：`POST ... -> 201`，`"event_id": "evt-f93338ad-…"`、`"sync_status": "synced"`。

### AC2 mock 返回 500 时课期仍保存，sync_status=failed 且重试队列有记录
- 用例：`test_ac2_activity_500_keeps_session_and_enqueues_retry`
- 判据：响应 201 且 `event_id is None`、`sync_status == "failed"`、`status == "scheduled"`；`GET /api/internal/academy/sync-retries` 恰 1 行，`operation=create`、`status=pending`、`attempts=1`、`max_attempts=5`、`last_error` 含 `mock activity error 500`。

### AC3 名额改到小于已报名人数时返回 422 并给出已报名数
- 用例：`test_ac3_capacity_below_enrolled_returns_422_with_enrolled_count`
- 判据：插入 12 条 enrolled 报名 → `PATCH {"capacity":10}` 返回 **422**，`detail.code=capacity_below_enrolled`、`detail.enrolled=12`；边界 `capacity=12` 返回 200 且 `enrolled_count=12`。

### AC4 audience 三种取值分别映射为正确的活动可见范围
- 用例：`test_ac4_audience_maps_to_activity_visibility`（参数化 3 组）+ `test_ac4_unknown_audience_is_rejected`
- 判据：`member_only→members_only`、`public→public`、`invite_only→closed_door`，断言的是**实际发给活动模块的 payload**，不是本地枚举；未知取值 422。

### 补充证据
| 项 | 用例 | 判据 |
|---|---|---|
| 改时间/场地/名额 → PATCH 活动 | `test_patch_time_venue_capacity_syncs_activity` | `activity.patches()` 恰 1 次，`event_id` 与创建时一致，payload 为新值 |
| 非同步字段不触发调用 | `test_patch_without_sync_fields_does_not_call_activity` | `len(activity.calls)` 不变 |
| 取消发事件且只发一次 | `test_cancel_sets_status_and_emits_event_once` | 发件箱 1 行 `academy.session.cancelled`；二次取消 409 且仍 1 行 |
| 列表过滤 + 软删除 | `test_list_filters_status_and_excludes_soft_deleted` | 软删后 total=1、`status=scheduled` 过滤后 total=0 |
| 退避序列 | `test_backoff_is_exponential` | `[30, 60, 120, 240, 480]` 秒 |
| 5 次上限 | `test_retry_stops_after_five_attempts` | 第 5 次后 `status=failed`、`stats.failed==1`，之后 `picked==0` |
| 真 HTTP POST/PATCH | `test_http_activity_client_posts_and_patches` | 方法与 URL 正确：`POST /api/internal/events`、`PATCH /api/internal/events/evt-123`，Bearer 头带上 |
| 500 抛错 | `test_http_activity_client_raises_on_500` | 抛 `ActivityError(status_code=500)` |

## 3. 复跑命令（审阅方三步即可）

```bash
git clone <本仓地址> && cd 1898-academy-sessions
pip install -r requirements.txt
pytest -q                              # 期望 17 passed
python scripts/demo_offline.py         # 期望五段演练全绿，末行打印活动模块调用次数
```

`EVIDENCE/pytest_output.txt` 与 `EVIDENCE/demo_offline_output.txt` 是本轮两次实跑的原始输出（未删改）。

## 4. 关键实现口径（审阅容易误判处）

1. **先落库再同步**：`create_session` 先 `flush()` 拿到课期 id，再调活动模块 —— 保证同步失败不丢课期（AC2 成立的前提）。
2. **重试计数口径**：首次同步失败即计 `attempts=1`，之后每次重试 +1，达 `max_attempts=5` 置 `failed`；退避 = `base × 2^(attempts-1)`，基数 `RETRY_BASE_SECONDS=30`。
3. **可见范围映射只有一张表**（`app/audience.py`），测试断言的是发给活动模块的 payload，换活动模块 token 只改这张表。
4. **取消不重复发事件**：状态机 `scheduled → cancelled` 单行，二次取消 409，发件箱不会重复。
5. **时间列 `UTCDateTime`**：入库存 naive UTC、出库还原带时区，规避 SQLite 与 PG 行为差异（首版曾因 naive/aware 混用在重试用例上失败，已修）。
6. **零真实数据**：标题/场地/会员 ID 全为虚构示例；无客户名；密钥只从环境变量读。

## 5. 与外部工单的边界

- S2-IAM：`X-Org-Id` 由网关解析，接 IAM 时只替换 `app/api.py::get_org`。
- 活动模块：`ACTIVITY_BASE_URL` 指向真服务即切换，课期侧零改动。
- S3-MINI：报名数读本地桩表 `academy_enrollments`，接真实报名后改为查会员端接口（AC3 判定逻辑不变）。
- 课期取消的通知与退权益：本单只发 `academy.session.cancelled`，由后续工单消费。
