# 商机权限矩阵与数据范围（S2-CRM-054）

会员空间平台的招商商机权限层实现：**数据范围**、**金额可见性**、**撞单检查字段投影**、
**漏斗汇总一致性**。权限判定不写在代码里，全部由 `crm/permissions/matrix/opportunity.yaml`
驱动 —— 改矩阵即改行为，代码不含任何角色的硬编码分支。

本仓库只包含权限层与配套测试，独立可跑；不依赖平台其他工单的运行实例。

---

## 一、交付物对照

| 需求交付物 | 落点 |
|---|---|
| `apply_opportunity_scope` 与金额可见性过滤 | `crm/permissions/scope.py` |
| `opportunity.yaml` 权限矩阵 | `crm/permissions/matrix/opportunity.yaml` |
| 参数化权限测试 | `tests/test_matrix_spec.py`、`tests/test_matrix_combinations.py` |
| README（运行与测试方法） | 本文件 |

---

## 二、目录结构

```
crm/
  config.py                    配置：连接参数一律离散环境变量注入，无写死凭证
  db.py                        SQLAlchemy 2.0 engine / session
  models.py                    Opportunity、AppUser(IAM 桩) 及三张留痕表
  iam.py                       IAM 桩：X-User-Id → {id, org_id, role, site_ids}
  main.py                      FastAPI 应用装配 + /healthz
  api/
    schemas.py                 请求模型
    opportunities.py           列表(含 summary)/详情/建档/强制建档/编辑/推进/删除/合并/历史/阶段历程
    duplicates.py              撞单检查（按角色裁剪字段投影）
  permissions/
    matrix/opportunity.yaml    ★ 权限矩阵唯一真源
    matrix_loader.py           矩阵装载、校验、mtime 缓存、判定入口
    scope.py                   ★ apply_opportunity_scope 与金额可见性
migrations/versions/0001_init.py   Alembic 初始迁移（与 ORM 定义逐列一致）
tests/
  spec_table.py                需求原文 → 规则表（人工逐条转写，独立于 YAML）
  test_matrix_spec.py          YAML 与规则表逐项比对
  test_matrix_combinations.py  角色 × 动作，逐个打真接口
  test_acceptance.py           验收条款 AC2 / AC3 / AC4
  test_scope_lifecycle.py      跨 org、场地范围、软删除、阶段过滤、合并、历史裁剪
scripts/
  test.sh                      一键跑测试
  mutation_check.py            变异测试：故意破坏每道闸门，确认用例会红
```

---

## 三、运行

### 3.1 起数据库

```bash
cp .env.example .env          # 填 CRM_DB_PASSWORD
docker compose up -d db
```

数据库镜像为 `pgvector/pgvector:pg16`（PostgreSQL 16 + pgvector），宿主端口 `55432`。
`vector` 扩展在初始迁移中创建，供后续语义去重预留，本单未启用。

### 3.2 建表

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
set -a; . ./.env; set +a
alembic upgrade head
alembic downgrade base        # 回滚同样是通的
```

### 3.3 起服务

```bash
uvicorn crm.main:app --reload --port 8080
curl localhost:8080/healthz
# {"status":"ok","version":"1.0.0","policy_version":"2026-11-27","roles":[...]}
```

---

## 四、测试

测试连**真实 PostgreSQL 16**（不 mock 数据库，数据范围与汇总口径必须在 SQL 层生效）：
首次运行自动建 `crm_test` 库并建表，每个用例前清库重灌基线数据。

```bash
bash scripts/test.sh                    # 默认 python3，可用 PYTHON=... 覆盖
bash scripts/test.sh -k acceptance      # 只跑验收条款
```

当前结果（PostgreSQL 16.16，本机实测）：

```
139 passed, 1 warning in 7.84s
```

| 文件 | 用例数 | 覆盖 |
|---|---:|---|
| `test_matrix_spec.py` | 76 | 6 角色 × 9 个判定位 + 数据范围 + 撞单投影 + 阶段图，逐项与需求转写表比对 |
| `test_matrix_combinations.py` | 44 | 6 角色 × 6 动作打真接口，另含推进维度与非法流转 |
| `test_acceptance.py` | 3 | AC2 本人商机汇总、AC3 viewer 无金额、AC4 撞单投影 |
| `test_scope_lifecycle.py` | 16 | 跨 org 隔离、场地范围、阶段过滤、软删除、合并、历史金额裁剪 |

### 变异测试（证明用例不是恒真）

```bash
set -a; . ./.env; set +a
PYTHONPATH=$PWD python scripts/mutation_check.py
```

逐条破坏权限闸门后重跑全量用例，每轮都必须在预期位置变红，跑完自动还原并校验 sha256：

| 变异 | 破坏点 | 结果 |
|---|---|---|
| M1 | 去掉 org 隔离 | 2 个用例变红 |
| M2 | 去掉 site 范围过滤 | 3 个用例变红 |
| M3 | 去掉 sales 的 owner 过滤 | 3 个用例变红 |
| M4 | 金额可见性恒为真 | 2 个用例变红 |
| M5 | 汇总金额对 viewer 下发 | 1 个用例变红 |
| M6 | 撞单最小投影失效 | 2 个用例变红 |
| M7 | 去掉 finance 阶段过滤 | 3 个用例变红 |

> M2 是本轮补的：原先「sales 看不到第二个场地」这条用例，挡住它的是 owner 过滤而不是
> site 过滤，属假绿。现改用 `ops_manager`（`owner_scope=all`、无 stage 过滤、只挂 S1）
> 隔离场地闸门，变异后必红。

---

## 五、权限矩阵

`crm/permissions/matrix/opportunity.yaml` 是唯一真源。六个角色、四个维度：

| 角色 | 场地范围 | 负责人范围 | 阶段范围 | 金额 |
|---|---|---|---|---|
| `org_admin` | 全 org | 全部 | 全部 | 可见 |
| `ops_manager` | 本人 site_ids | 全部 | 全部 | 可见 |
| `sales_lead` | 本人 site_ids | 全部 | 全部 | 可见 |
| `sales` | 本人 site_ids | 仅本人 | 全部 | 可见 |
| `finance` | 本人 site_ids | 全部 | 仅 `won` | 可见 |
| `viewer` | 本人 site_ids | 全部 | 全部 | **置 null + `amount_hidden=true`** |

动作位（9 个）：

| 角色 | read | write | duplicate_check | advance(as_owner) | advance(by_role) | force_create | delete | merge |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| `org_admin` | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| `ops_manager` | ✓ | ✓ | ✓ | ✓ | — | — | — | — |
| `sales_lead` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `sales` | ✓ | ✓ | ✓ | ✓ | — | — | — | — |
| `finance` | ✓ | — | ✓ | — | — | — | — | — |
| `viewer` | ✓ | — | ✓ | — | — | — | — | — |

两条总口径：

1. **任何角色先受 org 约束**，矩阵不提供跨 org 的口子；
2. **`org_admin` 不受场地限制**（`site_scope: all_in_org`），其余角色只能看本人 `site_ids`。

矩阵装载时校验 `site_scope` 与 `owner_scope` 的取值集合，写错直接抛 `MatrixError`，不会静默降级。

---

## 六、实现要点

### 6.1 数据范围在 SQL 层生效

`apply_opportunity_scope(query, user)` 只往 select 上加 `where`，不做「先查全量再内存过滤」——
越权数据不进应用内存：

```python
scoped = query.where(Opportunity.org_id == user.org_id,
                     Opportunity.deleted_at.is_(None))
if pol.site_scope == "own_sites":
    scoped = scoped.where(Opportunity.site_id.in_(list(user.site_ids)))
if pol.owner_scope == "own":
    scoped = scoped.where(Opportunity.owner_id == user.id)
if pol.stage_in:
    scoped = scoped.where(Opportunity.stage.in_(list(pol.stage_in)))
```

撞单检查是唯一的例外：判重的意义就是发现「同场地、他人名下、尚未成交」的重复，
因此该入口显式传 `ignore_owner_scope=True, ignore_stage_filter=True`。
该放宽**不**突破 org 与 site 边界，也不扩大字段投影。

### 6.2 越权一律 404，权限不足才 403

- 对象不可见（不存在 / 跨 org / 超出场地 / 超出负责人 / 已软删 / 被阶段过滤）→ **404**，不泄露存在性；
- 角色本身无此动作（如 `sales` 删除、`viewer` 写入）→ **403**；
- 状态冲突（撞单、非法阶段流转）→ **409**；参数非法（非法 stage、指派不存在的人）→ **422**。

### 6.3 金额只在一处裁剪

`apply_amount_visibility()` 是唯一的裁剪出口，详情、列表、历史全部经它：

- `amounts.visible=true`：原样返回；
- `visible=false`：`expected_first_year_amount_fen` / `weighted_amount_fen` 置 `null`，
  并附 `amount_hidden=true`；
- 历史接口对金额类字段的 `old_value` / `new_value` 同样置 `null`。

### 6.4 汇总与列表同一口径

列表与 `summary` 共用 `_build_list_filters()` 产出的同一组过滤条件，
再各自叠加 `apply_opportunity_scope` —— 两者口径不可能漂移。
`viewer` 的 `summary` **不返回** `amount_total_fen` / `weighted_total_fen` 两个键（不是返回 0）。

### 6.5 撞单检查的字段投影

| 角色 | 投影 |
|---|---|
| `sales` | `id`、`stage`、`owner_id`、`owner_name` —— 不含金额、不含空间需求 |
| 其他角色 | 上述 + `site_id`、两个金额字段、`space_requirement` |

投影定义在矩阵的 `duplicate_check_projection` 下，与动作位同源。

### 6.6 阶段流转

`stage_graph` 定义在矩阵里，推进接口只接受有向边：
`new→qualified/lost`、`qualified→proposal/lost`、`proposal→won/lost`、`lost→qualified`、`won` 为终态。
越过有向边返回 409。推进权限为「负责人本人」或矩阵 `advance_stage.by_role=true` 的角色。

---

## 七、接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/crm/opportunities` | 列表 + `summary`（数量/阶段分布/金额，均限可见范围） |
| GET | `/api/crm/opportunities/{id}` | 详情 |
| POST | `/api/crm/opportunities` | 建档（撞单则 409） |
| POST | `/api/crm/opportunities/force-create` | 强制建档，跳过撞单拦截 |
| PATCH | `/api/crm/opportunities/{id}` | 编辑（字段变更留痕） |
| POST | `/api/crm/opportunities/{id}/advance` | 阶段推进 |
| DELETE | `/api/crm/opportunities/{id}` | 软删除 |
| POST | `/api/crm/opportunities/merge` | 合并（金额累加、source 软删留痕） |
| GET | `/api/crm/opportunities/{id}/history` | 字段变更历史 |
| GET | `/api/crm/opportunities/{id}/stage-timeline` | 阶段历程 |
| POST | `/api/crm/opportunities/duplicate-check` | 撞单检查（待建商机） |
| GET | `/api/crm/opportunities/{id}/duplicates` | 撞单检查（已存在商机） |
| GET | `/healthz` | 健康检查，含矩阵版本与角色清单 |

统一字段：`id(UUID)`、`org_id`、`site_id`、`created_at`、`created_by`、`updated_at`、
`deleted_at`（软删除）。金额一律以「分」存 `BigInteger`，不用浮点。

---

## 八、对接点（S2-IAM）

本单依赖 S2-IAM 的身份、角色与数据范围，当前以**接口桩**先行，契约固定为：

```python
CurrentUser(id: str, org_id: UUID, role: str, site_ids: tuple[UUID, ...], display_name: str)
```

- 桩实现：`crm/iam.py` 的 `load_user()` 读本地 `app_user` 镜像表，请求头 `X-User-Id` 传用户 id；
- 接真实 IAM 时**只替换 `load_user()` 的取数来源**（改成解析 IAM 签发的 token），
  `crm/permissions/*` 与 `crm/api/*` 不动；
- 角色取值必须落在矩阵的六个 key 内，否则装载报 `MatrixError`。

---

## 九、验收对照

| 条款 | 内容 | 证据 |
|---|---|---|
| AC1 | `opportunity.yaml` 每组合都有用例，pytest 全绿 | `test_matrix_spec.py`（76）+ `test_matrix_combinations.py`（44），全量 `139 passed` |
| AC2 | 两名 sales 各 3 条商机，各自 `summary.amount_total_fen` 只等于自己 3 条之和 | `test_acceptance.py::test_ac2_sales_summary_counts_only_own_three` |
| AC3 | viewer 的详情、列表与 summary 都不出现金额数值 | `test_acceptance.py::test_ac3_viewer_sees_no_amount_values`（递归扫描全部金额键） |
| AC4 | 撞单检查返回给 sales 的数据不含金额字段 | `test_acceptance.py::test_ac4_duplicate_check_hides_amounts_for_sales` |

AC2 的隔离性：两名 sales 的金额和刻意不同（600 000 与 1 500 000 之外的自造数据），
一旦汇总越权统计，数值必然对不上，不会出现「巧合相等」的假通过。

---

## 十、边界与限制

1. **认证为桩**：`X-User-Id` 直传，无签名校验，仅用于联调与本单自测；生产必须换成 IAM token。
2. **Redis 未启用**：`docker-compose.yml` 起了 redis 供后续工单使用，本单无缓存依赖。
3. **pgvector 仅预留**：迁移中建了 `vector` 扩展，语义去重不在本单范围。
4. **撞单判重为规则匹配**：公司名归一化（去空白、全角括号折半角、casefold）+ 空间需求字符串相等；
   不含模糊匹配与语义相似度。
5. **合并语义**：source 金额累加到 target，source 软删并写 `opportunity_merge_log`；不做字段级合并策略。

---

## 十一、数据与保密

- 全部数据为虚构样例（"甲科技""乙数据"一类占位公司名），不含任何真实个人信息或企业信息；
- 仓库不含客户名称、真实联系方式、凭据或平台内部结算数字；
- 连接参数只从环境变量读取，`.env` 已在 `.gitignore` 中，仓库仅提供 `.env.example`。
