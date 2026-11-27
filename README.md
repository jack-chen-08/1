# 五类来源虚构样例数据生成器（S2-IMP-027）

面向「会员空间平台 · 历史数据清洗与导入」的**样例数据生成器**与**预埋缺陷答案文件**。
一份代码可复现出全套脏数据，配套五个映射器可把预埋缺陷全部检出，用于验证清洗/导入链路。

- 运行环境：Python 3.11+（实测 3.12.13），依赖仅 `openpyxl`（写 xlsx）与 `pytest`（测试）
- 一键生成：`python gen_import_samples.py --seed 20260101 --out samples`
- 一键自检：`python check_samples.py --samples samples`

## 1. 产出文件

| 文件 | 数据量 | 说明 |
|---|---|---|
| `members.csv` | 300 行 | 会员名册：120 家企业（100 家 active）/ 300 名联系人，每行一名联系人，企业列随行冗余 |
| `contracts.csv` | 165 行 | 合同台账 160 份 + 5 行预埋重复行；文件第 1 行为标题、第 2 行为空白（模拟业务系统导出脏格式） |
| `leases.xlsx` | 140 行 | 租约台账；含 **真实合并单元格**（xlsx 才能承载"合并"这一物理特征） |
| `unit_inventory.csv` | 180 行 | 单元清单，干净基线，不含预埋缺陷 |
| `activities.csv` | 900 行 | 活动记录，覆盖 60 场（60 场次 × 15 名参与人） |
| `interactions.csv` | 1500 行 | 互动记录，**GB18030 编码**（模拟老系统导出），数据区中部有 1 行空白 |
| `answer_key.json` | 69 条 | 预埋缺陷答案文件：代码 / 文件 / 物理行号 / 字段 / 说明，另有按代码汇总的 counts |

行号约定：**文件物理行号（1 基，含表头与标题行）**，与 `answer_key.json` 的 `rows` 字段完全一致。

## 2. 确定性（对应验收 1）

同一 `seed` 两次运行，所有单元格值与 `answer_key.json` 逐格一致：

```bash
python gen_import_samples.py --seed 20260101 --out /tmp/a
python gen_import_samples.py --seed 20260101 --out /tmp/b
python - <<'PY'
import csv, json
def cells(p, enc="utf-8"):
    with open(p, encoding=enc, newline="") as f:
        return [tuple(r) for r in csv.reader(f)]
for n in ("members.csv", "contracts.csv", "unit_inventory.csv", "activities.csv"):
    assert cells("/tmp/a/" + n) == cells("/tmp/b/" + n), n
assert cells("/tmp/a/interactions.csv", "gb18030") == cells("/tmp/b/interactions.csv", "gb18030")
assert json.load(open("/tmp/a/answer_key.json")) == json.load(open("/tmp/b/answer_key.json"))
print("determinism OK")
PY
```

实现保证：全程单实例 `random.Random(seed)`；不读时钟、不读环境变量、不遍历无序集合；
xlsx 只写值不加时间戳；`answer_key.json` 无生成时间字段。反证据：换 seed 数据必然不同（`tests/test_generator.py::test_ac1_different_seed_differs`）。

## 3. 虚构规则（对应验收 3）

- 企业名 100% 含「示例」前缀，120 个名称互不重复（断言：`test_ac3_company_names_all_fiction`）
- 手机号统一为 `1[3-9]0000####`，中间 4 位固定 `0000`（断言：`test_ac3_mobile_mid_four_zeros`，缺陷行由 answer_key 显式豁免）
- 邮箱统一 `@example.com` / `@example.net`
- 信用代码按 GB 32100-2015 算法生成合法校验位（缺陷行除外）
- 人员姓名由内置姓氏/名字表组合，不含任何真实个人

## 4. 预埋缺陷清单（对应验收 2）

共 **17 类 / 69 条**，`answer_key.json` 的 `counts` 与本表逐项一致（断言：`tests/test_answer_key.py::test_readme_counts_match_answer_key`）。

| 问题代码 | 含义 | 条数 | 落点 |
|---|---|--:|---|
| `FULLWIDTH_CHAR` | 全角字符 | 4 | members.csv · contact_name |
| `PHONE_FORMAT_VARIANT` | 号码多种写法（空格/横线/括号/点号/带 +86） | 6 | members.csv · mobile |
| `PHONE_SCIENTIFIC` | 号码被转成科学计数法 | 3 | members.csv · mobile |
| `CREDIT_CODE_CHECKSUM` | 信用代码校验位不符 | 5 | members.csv · credit_code |
| `DUPLICATE_ROW_IN_FILE` | 文件内重复行（成组） | 5 | contracts.csv |
| `CROSS_FILE_NAME_VARIANT` | 跨文件企业名称变体（同 member_id 不同名） | 10 | contracts.csv · company_name |
| `MERGED_CELL` | 合并单元格（真实 xlsx 合并区间） | 2 | leases.xlsx · company_name |
| `TITLE_ROW` | 表头之前的标题行 | 1 | contracts.csv 第 1 行 |
| `BLANK_ROW` | 空白行 | 3 | contracts.csv 第 2 行 / activities.csv / interactions.csv |
| `UNKNOWN_ENUM` | 未知枚举值 | 5 | members.csv · member_status |
| `MIXED_DATE_FORMAT` | 混合日期格式（`2024/07/01`、`20240702`、`2024.07.03`） | 9 | members / contracts / leases / activities |
| `LEASE_OVERLAP` | 租期重叠（同单元同场地） | 2 | leases.xlsx |
| `RENEWAL_CYCLE` | 续签链成环 | 1 | leases.xlsx · renew_from |
| `SITE_CONFLICT` | 场地冲突（同单元跨场地同时占用） | 1 | leases.xlsx · site_id |
| `UNMATCHED_ATTENDEE` | 参与人不在名册 | 3 | activities.csv |
| `ORPHAN_INTERACTION` | 孤儿互动（会员号不存在） | 4 | interactions.csv |
| `ID_NUMBER_IN_BODY` | 自由文本含 18 位证件号 | 5 | interactions.csv · content |
| **合计** | | **69** | |

## 5. 映射器与预演（对应验收 4）

`mappers/` 下五个映射器各管一类来源，共用 `mappers/base.py` 的读取与通用校验：

| 模块 | 覆盖来源 | 检出代码 |
|---|---|---|
| `mappers/members.py` | 会员名册 | FULLWIDTH_CHAR / PHONE_FORMAT_VARIANT / PHONE_SCIENTIFIC / CREDIT_CODE_CHECKSUM / UNKNOWN_ENUM / MIXED_DATE_FORMAT |
| `mappers/contracts.py` | 合同台账 | TITLE_ROW / BLANK_ROW / DUPLICATE_ROW_IN_FILE / CROSS_FILE_NAME_VARIANT / MIXED_DATE_FORMAT |
| `mappers/leases.py` | 租约台账 | MERGED_CELL / LEASE_OVERLAP / RENEWAL_CYCLE / SITE_CONFLICT / MIXED_DATE_FORMAT |
| `mappers/activities.py` | 活动记录 | UNMATCHED_ATTENDEE / MIXED_DATE_FORMAT / BLANK_ROW |
| `mappers/interactions.py` | 互动记录 | ORPHAN_INTERACTION / ID_NUMBER_IN_BODY / BLANK_ROW |

预演命令与实测输出（69/69 命中、0 误报）：

```bash
$ python check_samples.py --samples samples
answer_key 预埋：69 条 / 映射器检出：69 条
漏检：0 条   误报：0 条
...
结论：全部命中且无误报（AC4 达成）
```

判定口径：按 `(问题代码, 文件, 行号集合)` 三元组做集合比对，**漏检与误报都必须为 0**；
干净行不产生任何 error 级问题（`severity != "error"` 的仅 TITLE_ROW/BLANK_ROW/MERGED_CELL 三类结构性提示，且均已列入答案文件）。

## 6. 目录结构

```
gen_import_samples.py   生成器（单文件，可独立运行）
check_samples.py        五映射器预演 + 与 answer_key 逐条比对
mappers/                五个映射器 + 公共件
tests/                  AC1–AC4 断言（pytest）
samples/                默认 seed 的样例产出（已提交，便于直接查看）
reports/                AC1–AC4 实测输出留档
```

## 7. 已知边界

- 合并单元格只在 xlsx 中真实存在；CSV 无法承载，故租约台账固定为 xlsx。
- `answer_key.json` 记录的是**物理行号**，插入/删除行会使行号失效，需重新生成而非手改。
- 租期重叠判定采用闭区间（首尾相接视为重叠），与「同一单元不可同日双租」的业务口径一致。
- 名册按「行级」记录缺陷：同一企业的多行联系人可能只有一行带脏值（真实导出中即如此），跨行一致性不在本次映射器范围内。
- 本单交付的是**样例数据文件**，不是数据库表结构，因此未加 `org_id` / `created_by` / `updated_at` / `deleted_at` 等平台审计字段；字段集合按各来源单据的真实导出列设计（金额均已按「分」存整数：`amount_fen` / `rent_fen`）。

## 8. 运行与测试方法

环境：Python 3.11+（实测 3.12.13），仅两个依赖。

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 生成样例（默认 seed=20260101，输出到 samples/）
python gen_import_samples.py --out samples
#    自定义 seed / 输出目录
python gen_import_samples.py --seed 777 --out /tmp/samples_777

# 3. 五映射器预演：与 answer_key 逐条比对（全部命中且无误报时 exit 0）
python check_samples.py --samples samples

# 4. 跑 AC1–AC4 断言
python -m pytest tests -v

# 5. 重新生成 AC1–AC4 证据报告（写 reports/*.md）
python make_evidence.py
```

预期输出：`check_samples.py` 打印 17 类逐项「答案 / 检出」表并以 `结论：全部命中且无误报（AC4 达成）` 结束；`pytest` 输出 `10 passed`。
