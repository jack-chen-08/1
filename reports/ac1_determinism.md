# AC1 确定性实测：同一 seed 两次运行逐格比对

生成命令：`python gen_import_samples.py --seed 20260101 --out <dir>`（执行两次，目录 a / b）

| 文件 | 目录 a (sha256 前16) | 目录 b (sha256 前16) | 结论 |
|---|---|---|---|
| members.csv | `c11cff0d50233d28` | `c11cff0d50233d28` | 一致 |
| contracts.csv | `75e11b93c5240d93` | `75e11b93c5240d93` | 一致 |
| leases.xlsx | `5c652c4d6b6d8ea2` | `5c652c4d6b6d8ea2` | 一致 |
| unit_inventory.csv | `e9ed4f8897dd9d65` | `e9ed4f8897dd9d65` | 一致 |
| activities.csv | `c90ab11d2934c639` | `c90ab11d2934c639` | 一致 |
| interactions.csv | `e5710fc412e5249a` | `e5710fc412e5249a` | 一致 |
| answer_key.json | `479b1359058f5570` | `479b1359058f5570` | 一致 |

比对口径：CSV 按解析后的单元格值序列做 sha256；xlsx 按单元格值 JSON 做 sha256；answer_key.json 按文件字节。

**结论：7/7 个文件逐格一致 → AC1 达成。**
