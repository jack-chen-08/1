# 课期管理接口与活动模块同步（S6-ACAD-013）

会员空间平台 · 学院 v1 的课期（course session）后台接口：课期增删改查 + 创建/修改时同步到活动模块 + 同步失败进重试队列 + 取消时发出 `academy.session.cancelled` 事件。

技术栈：Python 3.11+ / FastAPI / SQLAlchemy 2（async）/ Pydantic 2 / PostgreSQL 16（本地与测试用 SQLite）。
本仓零真实数据：所有标题、场地、会员 ID 均为虚构示例。

## 1. 接口清单

前缀：`/api/admin/academy/courses/{course_id}/sessions`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `` | 列表，支持 `status=scheduled\|cancelled`、`limit`、`offset`，按开始时间升序，排除软删除 |
| POST | `` | 创建；同步调用活动模块创建活动并回填 `event_id` |
| PATCH | `/{sid}` | 局部修改；改时间/名额/场地等会同步 PATCH 活动 |
| POST | `/{sid}/cancel` | 取消：置 `status=cancelled` + 写事件发件箱；重复取消 409 |

运维入口：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/internal/academy/sync-retries/process` | 跑一轮到期重试（生产由定时任务每 30 秒调） |
| GET | `/api/internal/academy/sync-retries` | 查看重试队列 |

请求头 `X-Org-Id` 代表已解析的 org 上下文（见第 4 节），缺失返回 400。

```bash
curl -X POST localhost:8000/api/admin/academy/courses/$COURSE/sessions \
  -H 'X-Org-Id: '"$ORG" -H 'Content-Type: application/json' \
  -d '{"title":"产业资源对接实战","seq_label":"第 3 期",
       "starts_at":"2026-12-10T09:00:00+08:00","ends_at":"2026-12-10T12:00:00+08:00",
       "venue_name":"示例厅 A","capacity":40,"waitlist_capacity":10,
       "requires_approval":false,"audience":"member_only"}'
```

## 2. 运行与测试

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -q                     # 17 passed
python scripts/demo_offline.py  # 离线跑完四条验收，打印真实报文
uvicorn app.api:app --port 8000
```

环境变量（只从环境变量读，代码里无硬编码）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./academy_dev.db` | 生产填 `postgresql+asyncpg://...` |
| `ACTIVITY_BASE_URL` | `http://127.0.0.1:8099` | 活动模块地址 |
| `ACTIVITY_TOKEN` | 空 | 活动模块内部调用令牌 |
| `RETRY_MAX_ATTEMPTS` | `5` | 重试上限（需求规定 5） |
| `RETRY_BASE_SECONDS` | `30` | 指数退避基数：30/60/120/240/480 |

## 3. 活动模块对接点（本单以 mock 先行）

客户端实现在 `app/activities.py`，字段翻译集中在 `build_activity_payload()` 一处，可见范围映射集中在 `app/audience.py` 一张表。

| 本单动作 | 活动模块调用 |
|---|---|
| 创建课期 | `POST {ACTIVITY_BASE_URL}/api/internal/events`，body 含 `type=academy_course` |
| 改时间/名额/场地 | `PATCH {ACTIVITY_BASE_URL}/api/internal/events/{event_id}` |

创建时传入：标题（`课程名 + 空格 + 期次`）、`starts_at`/`ends_at`（ISO8601 带时区）、`venue_name`、`capacity`（名额）、`waitlist_capacity`（候补数）、`requires_approval`、`audience`、`org_id`、`site_id`。

audience → 活动可见范围（唯一映射表，活动模块若用别的 token 只改这一处）：

| 课期 audience | 业务含义 | 活动 audience |
|---|---|---|
| `member_only` | 会员专享 | `members_only` |
| `public` | 公开 | `public` |
| `invite_only` | 闭门会 | `closed_door` |

失败语义：活动模块返回 4xx/5xx 或网络异常 → 课期照常保存（`status=scheduled`、`event_id` 为空、`sync_status=failed`），落一行重试队列，响应体带 `sync_status=failed`。
重试：最多 5 次，第 n 次失败后等 `30 × 2^(n-1)` 秒，达上限标 `failed` 并保留 `last_error`；成功后回填 `event_id` 且 `sync_status` 转 `synced`。

**怎么换成真服务**：把 `ACTIVITY_BASE_URL` 指向活动模块工单产出的服务即可，课期侧零改动；本地演练用 `mock_activity.py`（`MockActivityClient` 可编程失败，或 `uvicorn mock_activity:mock_app --port 8099` 起假服务，`GET /_calls` 看收到的报文）。

## 4. 身份与数据范围对接点（S2-IAM）

本单不实现鉴权：`X-Org-Id` 头代表网关/IAM 已解析出的 org 上下文，路由内所有查询都以它做数据范围过滤（`org_id` 落到每条 SQL）。
接 IAM 工单时替换 `app/api.py::get_org` 这一个依赖函数为 JWT 解析 + 角色校验即可，业务层不动。

## 5. 数据模型

统一字段：`id`(UUID) / `org_id` / `site_id` / `created_at` / `created_by` / `updated_at` / `deleted_at`（软删除）。

| 表 | 用途 |
|---|---|
| `academy_course_sessions` | 课期主体；`event_id` 关联活动；`sync_status` = synced/failed |
| `academy_enrollments` | 报名记录**本地桩**，只用于名额校验（真实报名在 S3-MINI） |
| `academy_sync_retry` | 同步重试队列：`attempts`/`max_attempts`/`next_attempt_at`/`status` |
| `academy_outbox_events` | 事件发件箱：本单只落 `academy.session.cancelled` |

时间列统一 `UTCDateTime`（入库存 naive UTC，出库还原带时区 UTC），避免 SQLite 与 PG 行为差异。
金额类字段本单不涉及；若后续加收费，按分存整数。

迁移：`init_models()` 用 `create_all` 起步（本地/测试够用）；生产接 Alembic，第一次迁移即按上表建，之后只加不删。

## 6. 业务规则

1. 创建校验：`ends_at > starts_at`、`capacity >= 1`、`waitlist_capacity >= 0`、`audience` 三取值之一（否则 422）。
2. 名额下限：`capacity` 不得小于已报名人数（`enrolled` 状态的报名数），违反返回 **422** 且 body 带 `enrolled` 实际值；等于已报名人数放行。
3. 已取消课期不可 PATCH → 409。
4. 取消：只改状态 + 发事件，不重复发（第二次 409）；通知与退权益由「课期取消」工单消费该事件。
5. 只改 `seq_label` 等非同步字段不会调用活动模块。

## 7. 测试覆盖（对应验收）

| 验收 | 用例 |
|---|---|
| AC1 创建后 mock 收到一次创建、`event_id` 回填 | `test_ac1_create_triggers_one_activity_create_and_backfills_event_id` |
| AC2 mock 500 时课期仍保存、`sync_status=failed`、重试队列有记录 | `test_ac2_activity_500_keeps_session_and_enqueues_retry` |
| AC3 名额小于已报名 → 422 且给出已报名数 | `test_ac3_capacity_below_enrolled_returns_422_with_enrolled_count` |
| AC4 audience 三取值映射正确（参数化） | `test_ac4_audience_maps_to_activity_visibility`（3 组）+ `test_ac4_unknown_audience_is_rejected` |
| 补充 | PATCH 同步活动、非同步字段不调活动、取消事件只发一次、列表过滤与软删除、退避序列、5 次上限、真 HTTP 客户端 POST/PATCH、500 抛错 |

## 8. 已知边界（本单不做）

- 通知、退权益、候补转正（课期取消 / 报名工单）。
- 活动模块的活动内容管理（活动模块工单）。
- 权限矩阵与角色（S2-IAM 工单）。
- 前端页面（工作台工单）。
