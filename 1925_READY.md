# 交接单 —— 【S3-KB-015】1925 检索与原文查看的可见范围过滤

交付方：default（沈确）　｜　接收方：cluster-deepseek（梁文砚）
平台侧动作（precheck / 提交）按分工归**接收方**执行，本侧未跑、未提交。

## 1. 分支与提交

| 项 | 值 |
| --- | --- |
| 仓库 | `git@github.com:jack-chen-08/1.git`（public） |
| 分支 | `refs/heads/1925` |
| 代码提交 | `14bc08d0c5d154f4338958aa4a9c411abbcb0d6b` |
| 说明 | 本交接单为**该提交之后**的一次追加提交，只新增本文件，不改动代码、测试与文档任何一行；分支头 sha 以 `git ls-remote --heads origin 1925` 为准 |
| 基线 | `main` 未触动，仍为 `f911ff93b5de327ba58940992ca60a6b288e3c01`；`1898` / `2917` / 待交付单均未触碰 |

匿名回读已验：不带任何凭证 `git clone https://github.com/jack-chen-08/1.git -b 1925` 成功，
克隆副本内 `pytest -q` → **69 passed**，`mutation_check.py` → **7/7 全红**，
且与本地工作副本 `diff -r` 无差异。

## 2. 文件清单（39 个文件 / 2973 行）

| 路径 | 行数 | sha256 前 16 |
| --- | --- | --- |
| .env.example | 7 | 88c20b82b3418da6 |
| .gitignore | 9 | 8fa7a865434c78ec |
| EVIDENCE_INDEX.md | 58 | 6a913a035b4d5406 |
| README.md | 196 | f4aa85ae875c7af7 |
| alembic.ini | 40 | c9451097157855ac |
| kb/__init__.py | 5 | 6e9a2e4d2b01b995 |
| kb/api/__init__.py | 1 | 5384bfdb2df380b6 |
| kb/api/documents.py | 93 | 984da6488f82d162 |
| kb/api/schemas.py | 65 | 9052791cdd120588 |
| kb/api/search_api.py | 40 | bfa63591fcc318c1 |
| kb/api/sources.py | 115 | 63653635f13c00b4 |
| kb/config.py | 56 | 5de749ffa0bff7e2 |
| kb/db.py | 55 | bcb0711d549013ab |
| kb/embedding.py | 55 | a3b327421699831b |
| kb/iam.py | 105 | 1667a161fde060b9 |
| kb/main.py | 27 | c787cd786446215e |
| kb/models.py | 143 | 32494b530672047e |
| kb/policy/__init__.py | 1 | 5384bfdb2df380b6 |
| kb/policy/loader.py | 141 | 249d2a5f0c5a1fb4 |
| kb/policy/visibility_matrix.yaml | 56 | a8ae905d02d3bc51 |
| kb/search.py | 165 | b3a9e32b7994cece |
| kb/visibility.py | 129 | 332efd71541e9510 |
| migrations/env.py | 62 | 3b525438dff0a527 |
| migrations/script.py.mako | 25 | 3692e71f3ed37880 |
| migrations/versions/7814f60fba00_init_kb_schema.py | 100 | a972f7818f80d0d9 |
| pytest.ini | 6 | 9367e77534441117 |
| scripts/mutation_check.py | 166 | 248dd1ed275597ac |
| scripts/test.sh | 13 | e48f79927db6fab0 |
| scripts/verify_schema_parity.py | 94 | 1ac41c128088b23d |
| tests/__init__.py | 1 | 5384bfdb2df380b6 |
| tests/conftest.py | 96 | e5c46cde05c2cfda |
| tests/factory.py | 110 | 302955c64da71efe |
| tests/spec_table.py | 46 | 46c06f769ac49e52 |
| tests/test_member_isolation.py | 100 | 2aca7768defcc77a |
| tests/test_scope.py | 111 | daaa7357453b6301 |
| tests/test_source_404.py | 115 | 56b71b1f3d2cee66 |
| tests/test_sql_prefilter.py | 124 | cc731ab7fa2e86ca |
| tests/test_visibility_matrix.py | 96 | 2c909b4b7fed761d |
| tests/test_visibility_sync.py | 146 | 908afb36b26fdf73 |

复算命令：`git ls-files | sort | xargs -I{} sh -c 'printf "%s %s %s\n" {} $(wc -l < {}) $(sha256sum {} | cut -c1-16)'`

## 3. 真实测试输出原文

### 3.1 全量测试（连跑 3 轮）

```
$ python -m pytest -q
69 passed, 1 warning in 7.95s
69 passed, 1 warning in 7.93s
69 passed, 1 warning in 7.76s
```

warning 为 `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`，
来自第三方库，与本次改动无关。

分文件：

```
tests/test_visibility_matrix.py          34 passed, 1 warning in 2.86s
tests/test_member_isolation.py            4 passed, 1 warning in 3.02s
tests/test_visibility_sync.py             5 passed, 1 warning in 0.63s
tests/test_source_404.py                  6 passed, 1 warning in 0.80s
tests/test_sql_prefilter.py              12 passed, 1 warning in 0.87s
tests/test_scope.py                       8 passed, 1 warning in 0.93s
```

### 3.2 变异测试

```
$ python scripts/mutation_check.py
[M1] 去掉 audience 闸门（会员将看到 internal 切片） → RED  ✔
[M2] 去掉岗位交集闸门（visibility_roles 失效） → RED  ✔
[M3] 去掉会所交集闸门（visibility_sites 失效） → RED  ✔
[M4] 去掉类别白名单（价格与政策不再限主管及以上） → RED  ✔
[M5] 去掉 published 状态闸门（下线文档仍可读） → RED  ✔
[M6] 切片同步写错范围（文档改了、切片没改） → RED  ✔
[M7] 前后文查询不过滤（从上下文绕过可见范围） → RED  ✔

全部 7 项变异均按预期变红，源文件已无损还原。
```

### 3.3 模式一致性（alembic 建库 vs ORM create_all）

```
$ python scripts/verify_schema_parity.py --left kb_mig1925 --right kb_test
列数：kb_mig1925=39  kb_test=39
索引数：kb_mig1925=7  kb_test=7
结论：模式一致。
```

迁移双向可跑：`alembic upgrade head` → 建 3 表 + 7 索引；`alembic downgrade base` → 仅剩 `alembic_version`。

## 4. 验收标准逐条对应

| # | 验收标准 | 实现落点 | 用例 | 实测结果 |
| --- | --- | --- | --- | --- |
| 1 | 5 岗位 × 6 类别的权限矩阵测试全部通过 | `kb/policy/visibility_matrix.yaml` + `kb/visibility.py` | `tests/test_visibility_matrix.py` | 30 个单元格逐一判定：26 可见 / 4 不可见，另 4 条矩阵配置交叉校验；共 34 passed |
| 2 | 会员对 50 条虚构查询的召回中内部切片数为 0 | `kb/visibility.py`（会员分支） | `tests/test_member_isolation.py` | 50 条 × 2 模式 = 100 次检索，内部切片命中 **0**；每组均断言"确实召回该查询对应内容"（防空跑），并有员工侧 50/50 对照 |
| 3 | 修改可见范围后同事务内全部切片冗余字段已更新 | `kb/api/documents.py` | `tests/test_visibility_sync.py` | 成功路径 4 片全量同步且逐字段核对；异常路径在 commit 前抛错，文档 3 字段 + 切片 4 字段全部回退 |
| 4 | 无权查看返回 404 且响应体与不存在一致 | `kb/api/sources.py` | `tests/test_source_404.py` | 不存在 / 已下线 / 已软删除 / 无权查看 四路径 `r.content` **逐字节相同** |
| 5 | 两种检索 SQL 中都包含可见范围条件 | `kb/search.py` | `tests/test_sql_prefilter.py` | 编译后 SQL 断言 6 个条件原子 + 位置在 WHERE 与 ORDER BY 之间；返回行与直接执行 SQL 的行集合完全一致 |

## 5. 自查

**无外部依赖**（除 PostgreSQL 16 + pgvector + pg_trgm 外不调用任何外部服务，嵌入向量为本地确定性计算）；
**无真实数据**（语料全部虚构，无真实企业名/人名/手机号/身份证/客户名/内部金额）；
**无凭据**（仓内只有 `.env.example` 占位符，`.env` 已 gitignore，DSN 由离散变量运行时拼装，任何单条配置不含完整凭证串）。

已按上述三项对 `git ls-files` 全量扫描确认。

## 6. 给接收方的两条提示

1. **precheck 配额**：按分工本侧一次未跑，池子完整留给接收方；四张单共用一个账号池（6 次/小时）。
2. **踩坑记录（建议写进平台复检清单）**：SQLAlchemy `and_()` **不忽略 `None`**，
   `and_(cond, None)` 会编译成 `... AND NULL`，使查询静默返回空集。
   本侧变异测试 M3 第一版就踩了这个坑（测试红了但红的原因不对，属假红），已改为恒真占位。
   若后续有人在过滤条件里拼可选条件，务必用 `true()` 或跳过，不要塞 `None`。
