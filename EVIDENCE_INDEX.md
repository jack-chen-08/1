# 证据索引（AC ↔ 可复核证据）

面向机器核查：每条验收给出**判据 / 仓内纯文本证据 / 复跑命令 / 本轮实测数字**。
所有证据均为仓库内文本文件，无需看图。

| # | 客户验收原文 | 判据 | 仓内证据 | 复跑命令 | 本轮实测 |
|---|---|---|---|---|---|
| AC1 | 同一 seed 两次运行，所有单元格值与答案文件完全一致 | 7 个产出文件按单元格值做 sha256，两次运行逐格相同 | `reports/ac1_determinism.md`、`tests/test_generator.py::test_ac1_same_seed_identical_cells` | `python gen_import_samples.py --seed 20260101 --out /tmp/a && python gen_import_samples.py --seed 20260101 --out /tmp/b && python -m pytest tests -k ac1 -v` | 7/7 文件一致；2 个 AC1 用例通过 |
| AC2 | answer_key.json 的预埋缺陷数与 README 清单逐项一致 | 17 类逐项比对 counts 与总数 | `reports/ac2_answer_key_vs_readme.md`、`tests/test_answer_key.py::test_readme_counts_match_answer_key` | `python -m pytest tests -k readme -v` | 17 类全部一致，合计 69 = 69 |
| AC3 | 企业名全含「示例」、手机号中间 4 位为 0000 | 名册全量扫描 + 正则断言（缺陷行按 answer_key 豁免） | `reports/ac3_fiction_rules.md`、`tests/test_generator.py::test_ac3_company_names_all_fiction`、`::test_ac3_mobile_mid_four_zeros` | `python -m pytest tests -k ac3 -v` | 120 家企业名 100% 含「示例」；291 条非缺陷手机号 100% 符合 `1[3-9]d0000dddd`（另 9 条为预埋号码缺陷，已在 answer_key 登记） |
| AC4 | 用各映射器预演样例，answer_key 缺陷全部检出、干净行无 error | 按 (代码, 文件, 行号集合) 三元组做集合比对，漏检与误报都必须为 0 | `reports/ac4_mappers.md`、`reports/pytest_output.txt`、`tests/test_answer_key.py::test_ac4_mappers_hit_all_and_no_false_positive` | `python check_samples.py --samples samples && python -m pytest tests -v` | 检出 69/69，漏检 0，误报 0，干净行 error 0 |

## 一键复现全部证据

```bash
pip install -r requirements.txt
python gen_import_samples.py --seed 20260101 --out samples
python check_samples.py --samples samples     # AC4：逐条比对，期望「漏检 0 / 误报 0」
python make_evidence.py                       # 重写 reports/ac1..ac4 + pytest_output.txt
python -m pytest tests -v                     # 10 个用例全绿
```

## 产物规模（本轮实测）

| 项 | 数值 |
|---|---|
| 产出文件 | 7（6 份数据 + 1 份答案文件） |
| 数据行 | 名册 300 / 合同 165（160+5 重复）/ 租约 140 / 单元 180 / 活动 960（60 行场次形态 + 900 行参与人形态）/ 互动 1500 |
| 预埋缺陷 | 69 条，17 类 |
| 测试 | 13 个用例，全部通过（`pytest tests -q` → `13 passed`） |
