# AC4 映射器预演实测

命令：`python check_samples.py --samples samples`

| 问题代码 | answer_key | 映射器检出 |
|---|--:|--:|
| `BLANK_ROW` | 3 | 3 |
| `CREDIT_CODE_CHECKSUM` | 5 | 5 |
| `CROSS_FILE_NAME_VARIANT` | 10 | 10 |
| `DUPLICATE_ROW_IN_FILE` | 5 | 5 |
| `FULLWIDTH_CHAR` | 4 | 4 |
| `ID_NUMBER_IN_BODY` | 5 | 5 |
| `LEASE_OVERLAP` | 2 | 2 |
| `MERGED_CELL` | 2 | 2 |
| `MIXED_DATE_FORMAT` | 9 | 9 |
| `ORPHAN_INTERACTION` | 4 | 4 |
| `PHONE_FORMAT_VARIANT` | 6 | 6 |
| `PHONE_SCIENTIFIC` | 3 | 3 |
| `RENEWAL_CYCLE` | 1 | 1 |
| `SITE_CONFLICT` | 1 | 1 |
| `TITLE_ROW` | 1 | 1 |
| `UNKNOWN_ENUM` | 5 | 5 |
| `UNMATCHED_ATTENDEE` | 3 | 3 |
| **合计** | **69** | **69** |

- 漏检：0 条 []
- 误报：0 条 []

**结论：69 条预埋缺陷全部检出、干净行 0 误报 → AC4 达成。**
