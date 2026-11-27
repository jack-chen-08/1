# EVIDENCE_INDEX —— 【S3-KB-015】可见范围过滤

每条验收标准对应的判据、落点、复跑命令与本轮实际数字。
所有数字取自本机实跑，命令可直接复制复跑（需先按 README 第 6 节起库并配 `.env`）。

## 1. 总览

| 项 | 结果 |
| --- | --- |
| 测试用例 | **69 passed**（连跑 3 轮，均为 69 passed，无 flaky） |
| 变异测试 | **7 / 7 全部按预期变红**，源文件 sha256 无损还原 |
| 模式一致性 | alembic 建库 vs ORM create_all：**39 列 / 7 索引，完全一致** |
| 迁移 | `upgrade head` 与 `downgrade base` 双向可跑通 |

## 2. 逐条对应

| 验收标准 | 判据 | 用例 | 复跑命令 | 本轮实际数字 |
| --- | --- | --- | --- | --- |
| ① 5 岗位 × 6 类别的权限矩阵测试 | 每个单元格按需求原文（`tests/spec_table.py` 人工转写）判定可见/不可见 | `tests/test_visibility_matrix.py` | `pytest -q tests/test_visibility_matrix.py` | **34 passed**：30 个矩阵单元格 + 4 条矩阵配置交叉校验（岗位集合、类别集合、受限类别集合、rank 唯一性）。26 可见 / 4 不可见 |
| ② 会员对 50 条虚构查询的召回中内部切片数为 0 | 每条查询都必须真的召回到对应内容（防空跑），且召回结果 audience 必须全为 `member`；同一语料用员工上下文做对照，证明内部内容确实可召回 | `tests/test_member_isolation.py` | `pytest -q tests/test_member_isolation.py` | **4 passed**：50 条查询 × 2 种检索 = **100 次会员检索，内部切片命中 0**；对照组员工侧 50/50 条均召回内部切片、50/50 条均召回 member 切片 |
| ③ 改可见范围后同一事务内切片冗余字段已更新 | 成功路径：`chunks_synced` 等于切片数且逐片字段与文档一致；失败路径：commit 前抛异常，文档与切片**都**不变 | `tests/test_visibility_sync.py` | `pytest -q tests/test_visibility_sync.py` | **5 passed**：4 片文档全量同步；异常路径回滚后文档 3 个字段与 4 个切片 4 个字段均保持原值；越权（403）与他租户（404）各 1 例 |
| ④ 无权查看返回 404 且响应体与不存在一致 | 不存在 / 已下线 / 已软删除 / 无权查看 四条路径的响应**字节**完全相同 | `tests/test_source_404.py` | `pytest -q tests/test_source_404.py` | **6 passed**：4 组响应体逐字节比对（`r.content` 相等，非仅状态码）；另含 200 正常路径字段完整性 2 例 |
| ⑤ 两种检索 SQL 中都包含可见范围条件 | 按 PostgreSQL 方言编译成带字面量 SQL，断言条件原子存在且位于 WHERE 与 ORDER BY 之间；返回行与直接执行 SQL 的行集合一致 | `tests/test_sql_prefilter.py` | `pytest -q tests/test_sql_prefilter.py` | **12 passed**：4 组（员工/会员 × 关键词/向量）断言 6 个条件原子；员工侧岗位与会所闸门、会员侧无岗位闸门各 2 组；前置位置断言 2 组；向量阈值 1 组；行等价 1 组 |
| 附：岗位 / 会所 / 上下文 / 租户边界 | 各闸门的正面证据 | `tests/test_scope.py` | `pytest -q tests/test_scope.py` | **8 passed**：岗位隔离、会所隔离、会员空间隔离、上下文不泄露、跨租户、价格类 rank 边界 3 例 |

## 3. 变异测试明细

`python scripts/mutation_check.py`

| 编号 | 人为破坏 | 结果 | 变红用例 |
| --- | --- | --- | --- |
| M1 | 删掉 `audience` 条件 | RED ✔ | `test_member_recall_contains_zero_internal_chunks[keyword]` / `[vector]` |
| M2 | 删掉岗位交集闸门 | RED ✔ | `test_role_scoped_chunk_invisible_to_other_roles` |
| M3 | 删掉会所交集闸门（换恒真占位） | RED ✔ | `test_site_scoped_chunk_invisible_to_other_site`、`test_member_site_isolation` |
| M4 | 删掉类别白名单 | RED ✔ | `test_visibility_matrix.py` 6 例（含 4 个矩阵单元格） |
| M5 | 删掉 `status='published'` 闸门 | RED ✔ | `test_offline_document_is_indistinguishable` |
| M6 | 切片同步范围写反（`!=`） | RED ✔ | `test_sync_updates_every_chunk` |
| M7 | 前后文查询不过滤 | RED ✔ | `test_context_never_leaks_invisible_neighbour` |

脚本每轮都做「备份 → 改 → 跑 → 还原 → sha256 校验」，还原校验失败会单独报 `[!!]` 并计为失败。

> 注：M3 最初写成「删行留空 append」，导致 `and_(…, None)` 编译出 `AND NULL`，
> 全部查询都查不到东西——测试确实变红，但红的原因不是泄漏，属**假红**。
> 已改为恒真占位（`chunk.id.is_not(None)`），变红原因变为 `assert 200 == 404`（会员看到了他人空间内容），
> 这才是这条用例要守的东西。同类陷阱在后续订单中需注意：SQLAlchemy 的 `and_` **不会**忽略 `None`。

## 4. 源文件清单与校验

```bash
# 生成（交接时随单附上）
find kb tests scripts migrations -name '*.py' -o -name '*.yaml' | sort | xargs sha256sum
```

## 5. 复跑前置

1. PostgreSQL 16 + `vector` 0.8.7 + `pg_trgm` 1.6（`pgvector/pgvector:pg16` 镜像自带）
2. `.env` 中 5 个离散变量；测试库 `KB_TEST_DB_NAME` 存在且为空库
3. 依赖：`fastapi / sqlalchemy / psycopg / pgvector / alembic / pyyaml / pytest / httpx`
