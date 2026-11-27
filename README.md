# 【S3-KB-015】检索与原文查看的可见范围过滤

知识库切片的可见范围过滤，含关键词检索、向量检索与原文查看三条读取路径。
可见范围条件一律**在数据库里前置施加**，不存在先召回后过滤的路径。

- 技术栈：Python 3.12 / FastAPI / SQLAlchemy 2.0 / PostgreSQL 16 + pgvector + pg_trgm
- 单元与验收测试：69 例（真实 PostgreSQL，非 mock）
- 变异测试：7 道闸门逐个人为破坏，全部按预期变红

---

## 1. 交付清单

| 需求条目 | 落点 | 验收标准 |
| --- | --- | --- |
| `build_visibility_filter(user_ctx)` 生成 SQL 条件 | `kb/visibility.py` | 5 |
| 员工按岗位与会所过滤 | `kb/visibility.py` + `kb/policy/visibility_matrix.yaml` | 1 |
| 价格与政策类只对主管及以上开放 | 同上（`min_rank: 3`） | 1 |
| 会员只看到 `audience=member` 且所属空间可见 | `kb/visibility.py` | 2 |
| 过滤前置施加于关键词/向量检索 SQL | `kb/search.py` | 5 |
| 改可见范围同事务同步切片冗余字段 | `kb/api/documents.py` | 3 |
| 原文接口 404 不外泄存在性 | `kb/api/sources.py` | 4 |
| 5 岗位 × 6 类别矩阵测试 | `tests/test_visibility_matrix.py` | 1 |
| 50 条虚构查询召回隔离 | `tests/test_member_isolation.py` | 2 |
| 同事务同步（含回滚证明） | `tests/test_visibility_sync.py` | 3 |
| 404 响应体一致性 | `tests/test_source_404.py` | 4 |
| 两种检索 SQL 均含可见条件 | `tests/test_sql_prefilter.py` | 5 |

## 2. 规则

### 2.1 岗位 × 类别矩阵

真源是 `kb/policy/visibility_matrix.yaml`；代码里没有「哪个岗位不能看哪类」的分支，
改 YAML 即改行为。rank 越大权限越高。

| 岗位 | rank | 作业流程 | 培训材料 | 市场物料 | 常见问题 | 政策制度 | 价格与报价 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `staff` 普通员工 | 1 | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| `senior_staff` 高级员工 | 2 | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| `supervisor` 主管 | 3 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `site_manager` 会所负责人 | 4 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `org_admin` 平台管理员 | 5 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

共 30 个单元格：26 可见、4 不可见（两个受限类别 × 两个非主管岗位）。

### 2.2 三条附加条件

员工的最终可见 = 矩阵白名单 **且** 以下全部成立：

1. `audience ∈ {internal, member}`（员工两者都能看）
2. `visibility_roles` 为空，或与本人岗位有交集
3. `visibility_sites` 为空，或与本人会所有交集

会员的最终可见 = 以下全部成立：

1. `audience = member`
2. `visibility_sites` 为空，或包含本人所属空间
3. 文档未下线

### 2.3 需求未明处的口径（重要，请评审确认）

需求原文有三处没写死，本实现按以下口径落地，全部集中在 `kb/visibility.py` 与矩阵文件，
若要改口径只改这两处：

| # | 原判断 | 本实现口径 | 理由 |
| --- | --- | --- | --- |
| 1 | 「价格与政策类只对主管及以上开放」未说明是否也约束会员 | **只约束员工侧**。会员侧只按 `audience` 与所属空间收窄，不设类别门槛 | 会员看到的报价是面向客户的对外价，与内部报价策略不是同一份内容；且会员没有岗位，无法参与岗位门槛判断 |
| 2 | 会员是否受 `visibility_roles` 约束 | **不受约束**。`visibility_roles` 是员工侧字段 | 会员没有岗位概念，`visibility_roles` 对其无意义 |
| 3 | 「所属空间为会员可见」的具体含义 | 解释为切片 `visibility_sites` 为空（全空间）或包含会员所属空间 | 与员工侧会所过滤保持同一套字段语义，避免两套并行规则 |

## 3. 接口契约

### 3.1 `GET /api/kb/sources/{chunk_id}` —— 原文查看

返回切片正文、文档标题、版本、`heading_path`、页码，以及前后各一片上下文。

```json
{
  "chunk_id": "…",
  "doc_id": "…",
  "doc_title": "标题",
  "version": "v3",
  "heading_path": "第二章 > 2.1",
  "page_no": 12,
  "content": "切片正文",
  "prev": {"chunk_id": "…", "heading_path": "…", "page_no": 11, "content": "…"},
  "next": null
}
```

- 不存在 / 已下线 / 已软删除 / 无权查看 → 一律 `404`，响应体为 `{"detail":"not_found"}`，
  四条路径的响应字节完全一致（不用 403，避免暴露存在性）。
- `prev` / `next` 同样过可见条件：相邻切片无权查看时返回 `null`，绝不带出正文。
  否则可从上下文绕过可见范围（变异测试 M7 专门守这条）。

### 3.2 `POST /api/kb/search` —— 检索

```json
{"query": "续费政策", "mode": "keyword", "limit": 20}
```

`mode` 取 `keyword`（子串匹配，trigram 索引）或 `vector`（pgvector 余弦距离，阈值 0.6）。
两种模式的 SELECT 都在 WHERE 里挂 `build_visibility_filter()`，条件先于 `ORDER BY` 与 `LIMIT`。

### 3.3 `PATCH /api/kb/documents/{doc_id}/visibility` —— 改可见范围

```json
{"audience": "internal", "visibility_roles": ["supervisor"], "visibility_sites": []}
```

- 权限：`rank ≥ 3`（主管及以上）；会所负责人只能改本会所文档；平台管理员不受会所限制。
- 文档与**全部切片**的冗余字段在同一个事务里更新，只在最后 commit 一次；
  中途异常整笔回滚（响应里 `chunks_synced` 为受影响切片数）。

错误码：`404 not_found`（不存在/他租户/已删除）、`403 insufficient_role`、`403 out_of_site`。

## 4. 数据模型

| 表 | 作用 |
| --- | --- |
| `kb_document` | 可见范围的**唯一真源**：`audience`、`visibility_roles`、`visibility_sites`、`category`、`status` |
| `kb_chunk` | 切片，冗余上述四个字段的副本，供检索 SQL 直接比较，避免每查一次都 JOIN 出授权逻辑 |
| `app_user` | 身份桩（IAM 未交付），承载 `kind` / `role` / `rank` / `site_ids` |

冗余字段的代价是必须同步——这正是验收标准 3 守的东西：
`tests/test_visibility_sync.py` 既测「全量同步」，也测「中途抛异常时两边都不生效」。

统一字段：`id(UUID)`、`org_id`、`site_id`、`created_at`、`created_by`、`updated_at`、`deleted_at`（软删除）。

## 5. 前置施加的证据

三条读取路径共用同一个 `build_visibility_filter()`：

```python
conditions = [
    chunk.org_id == ctx.org_id,                    # 租户
    chunk.deleted_at.is_(None),                    # 软删除
    document.deleted_at.is_(None),
    document.status == "published",                # 下线
    chunk.audience.in_(pol.audiences),             # 受众
    chunk.category.in_(pol.categories),            # 类别白名单（矩阵换算）
    _array_empty_or_overlaps(chunk.visibility_roles, (ctx.role,)),
    _array_empty_or_overlaps(chunk.visibility_sites, pol.site_ids),
]
```

证明方式有三层，缺一层都不算数：

1. **SQL 文本断言**：把两种检索语句按 PostgreSQL 方言编译成带字面量的 SQL，
   断言条件原子（`kb_chunk.audience IN`、`cardinality(kb_chunk.visibility_roles)`、
   `&&` 交集运算等）出现在 `WHERE` 与 `ORDER BY` 之间。
2. **行等价断言**：`keyword_search()` 返回的行与直接执行同一条 SQL 的行，数量与顺序完全一致，
   证明应用层没有二次筛选。
3. **变异测试**：删掉任一闸门，对应用例必须变红。

## 6. 运行

```bash
# 1) 起数据库（需 pgvector 镜像）
docker run -d --name kb1925-pg -e POSTGRES_USER=kb -e POSTGRES_PASSWORD='<自设>' \
  -e POSTGRES_DB=kb -p 55433:5432 pgvector/pgvector:pg16

# 2) 配置（离散环境变量，任何单条都不含完整凭证）
cp .env.example .env && $EDITOR .env
createdb 或 psql 建 kb_test

# 3) 建表
alembic upgrade head                      # 正式 schema
# 测试库由 tests/conftest.py 自动 drop_all/create_all

# 4) 测试
python -m pytest -q                        # 69 passed
python scripts/mutation_check.py           # 7 项变异全红
python scripts/verify_schema_parity.py --left kb --right kb_test   # 模式一致性
```

依赖：`fastapi`、`sqlalchemy>=2`、`psycopg[binary]`、`psycopg-pgvector`（`pgvector`）、`alembic`、`pyyaml`、`pytest`、`httpx`。

## 7. 边界与未做

| 项 | 现状 | 后续 |
| --- | --- | --- |
| 嵌入模型 | `kb/embedding.py` 是确定性桩（字符 n-gram 哈希），仅用于离线可复现地测通链路 | 接入真实模型时替换 `embed()`，并由 `DEFAULT_MAX_DISTANCE` 重新标定阈值 |
| 身份 | `kb/iam.py` 从 `X-User-Id` 读 `app_user` | S2-IAM 交付后替换 `resolve_context()` 一处即可 |
| 关键词检索 | ILIKE 子串 + trigram，中文无需分词器 | 切片量级上千万时换 `zhparser`/`pg_bigm`，接口不变 |
| 混合检索 | 未做 | 需要融合排序时可加 `rerank`，但**过滤仍必须在 SQL 内** |
| 审计 | 未做 | 改可见范围属敏感操作，建议后续补审计日志 |

## 8. 自查

- **无外部依赖**：除 PostgreSQL（含 pgvector / pg_trgm 扩展）外不依赖任何外部服务；
  嵌入向量为本地确定性计算，不调用第三方 API。
- **无真实数据**：测试语料全部虚构（「A/B/C 会所」「虚构政策说明」等），
  不含真实企业名、人名、手机号、身份证、客户名或真实业务金额。
- **无凭据**：仓库内只有 `.env.example` 占位符；`.env` 已在 `.gitignore` 中；
  数据库 URL 由离散环境变量在运行时拼装，任何单条配置都不含完整凭证串。
