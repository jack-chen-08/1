# 证据索引（EVIDENCE_INDEX）

本单全部判据 → 代码/测试落点 → 复跑命令 → 本轮实测数字。数字均为本机真实执行结果，
复跑方式见每行「复跑」列；不接受「应该如此」的推断结论。

环境：PostgreSQL 16.16（容器 `pgvector/pgvector:pg16`，宿主端口 55432）、Python 3.12。

---

## 一、验收条款

| 判据 | 条款内容 | 落点 | 复跑命令 | 本轮实测 |
|---|---|---|---|---|
| AC1 | `opportunity.yaml` 每个角色×动作组合都有用例且 pytest 全部通过 | `tests/test_matrix_spec.py`（76 例，YAML↔需求转写表逐项比对）<br>`tests/test_matrix_combinations.py`（44 例，逐组合打真接口） | `bash scripts/test.sh` | `139 passed, 1 warning in 8.96s`（交付树内实测） |
| AC2 | 两名 sales 各有 3 条商机时，`summary.amount_total_fen` 只等于自己 3 条之和 | `tests/test_acceptance.py::test_ac2_sales_summary_counts_only_own_three` | `bash scripts/test.sh -k ac2` | 通过；两账号金额和不同（600000 / 1500000），越权统计必然对不上 |
| AC3 | viewer 的详情、列表、summary 都不出现金额数值 | `tests/test_acceptance.py::test_ac3_viewer_sees_no_amount_values` | `bash scripts/test.sh -k ac3` | 通过；递归扫描响应内全部金额键均为 `null`，且 `amount_hidden=true`；`summary` 无金额键 |
| AC4 | 撞单检查返回给 sales 的数据不含金额字段 | `tests/test_acceptance.py::test_ac4_duplicate_check_hides_amounts_for_sales` | `bash scripts/test.sh -k ac4` | 通过；`sales` 投影键集合恰为 `{id, stage, owner_id, owner_name}` |

## 二、需求条目 → 落点

| 需求原文要点 | 落点 | 复跑 |
|---|---|---|
| 只看本 org、本人 `site_ids` 内商机；`org_admin` 不受场地限制 | `crm/permissions/scope.py::apply_opportunity_scope` | `bash scripts/test.sh -k site_scope` |
| sales 只能读写自己负责的商机，他人商机 404 | `scope.py::get_visible_opportunity`（越权统一 404） | `-k "others_opportunity or cross_org"` |
| sales_lead / ops_manager 可读写本场地全部商机 | `opportunity.yaml` → `owner_scope: all` | `-k action_matrix` |
| finance 只读本场地 `stage=won` | `opportunity.yaml` → `stage_in: [won]` | `-k finance` |
| viewer 金额置 null 并附 `amount_hidden=true` | `scope.py::apply_amount_visibility` | `-k viewer` |
| 阶段推进允许负责人与 sales_lead | `opportunity.yaml` → `advance_stage: {as_owner, by_role}` | `-k advance` |
| force_create 只授 sales_lead / org_admin | `opportunity.yaml` → `force_create` | `-k action_matrix` |
| 删除与合并只允许 sales_lead / org_admin | `opportunity.yaml` → `delete` / `merge` | `-k action_matrix` |
| 列表 summary 只统计可见商机；viewer 的 summary 无金额字段 | `crm/api/opportunities.py::list_opportunities`（列表与汇总共用同一组过滤） | `-k summary` |
| 撞单检查对 sales 只返回 id / stage / 负责人 | `crm/api/duplicates.py` + `duplicate_check_projection.minimal_roles: [sales]` | `-k duplicate` |
| 矩阵写成 `crm/permissions/matrix/opportunity.yaml` | 该文件即唯一真源，代码无角色硬编码分支 | `-k matrix_spec` |
| 金额一律以「分」存整数 | `crm/models.py` → `BigInteger` | 迁移与 ORM 双侧核对见下 |
| 配置与密钥只从环境变量读取 | `crm/config.py::build_dsn`（离散变量拼装，无写死凭证） | 静态检查见第三节 |

## 三、工程质量核对

| 检查 | 方法 | 本轮结果 |
|---|---|---|
| 测试非恒真 | `scripts/mutation_check.py`：逐个破坏 7 道闸门后重跑全量 | 7/7 均在预期位置变红（2/3/3/2/1/2/3 个用例失败） |
| 源文件未被变异脚本改坏 | 脚本内 sha256 前后比对 | 一致 |
| 迁移与 ORM 逐列一致 | `alembic upgrade head` 后比对 `information_schema.columns` | 44 vs 43 列，唯一差异为 `alembic_version` 自身 |
| 迁移可回滚 | `alembic downgrade base` | 回滚后业务表 0 张 |
| 单次通过不作数 | 全量测试连续多轮复跑 | 3 轮一致通过（`7.95s / 7.86s / 8.47s` 段内） |
| 源码零告警 | `pytest` 警告汇总归属 | 剩余 1 条为第三方 `starlette.testclient` 弃用告警，本仓库代码 0 条 |
| 公开仓无敏感信息 | 正则扫描：内部金额/平台名/账号/凭据形态/手机号/身份证 | 全部 0 命中 |
| 内部金额与需求原文不入库 | `REQUIREMENT.md`、`problem_raw.json` 移至 `.intake/` 并写入 `.gitignore` | 已隔离，`git status` 无该目录 |

补记（真实修正，非事后美化）：首轮变异 M2「去掉 site 范围过滤」测试仍全绿 —— 原因是原有用例
由 owner 过滤而非 site 过滤挡住。已补 4 条隔离场地闸门的用例（`ops_manager` 维度、列表/汇总同口径、
finance 的 site×stage 叠加、跨场地建档 403），补后 M2 稳定 3 个用例变红。

## 四、复跑全部判据

```bash
cd <repo>
cp .env.example .env            # 填 CRM_DB_PASSWORD
docker compose up -d db
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
set -a; . ./.env; set +a
alembic upgrade head
bash scripts/test.sh            # 期望：139 passed
PYTHONPATH=$PWD python scripts/mutation_check.py   # 期望：7 行全 RED + 还原校验一致
```
