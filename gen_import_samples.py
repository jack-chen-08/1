#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_import_samples.py —— 会员空间平台「历史数据清洗与导入」五类来源虚构样例数据生成器

用法:
    python gen_import_samples.py --seed 20260101 --out samples

产出（--out 目录）:
    members.csv        会员名册（120 家企业 / 300 名联系人，其中 100 家 active）
    contracts.csv      合同台账 160 份（第 1 行标题、第 2 行空白，模拟导出脏格式）
    leases.xlsx        租约台账 140 条（含真实合并单元格）
    unit_inventory.csv 单元清单 180 个单元
    activities.csv     活动记录 900 行（覆盖 60 场）
    interactions.csv   互动记录 1500 条（GB18030）
    answer_key.json    预埋缺陷答案文件（来源 / 行号 / 字段 / 预期问题代码）

确定性: 全程 random.Random(seed), 不读时钟、不读环境、不迭代无序集合;
同一 seed 两次运行, 所有单元格值逐格一致（tests/test_determinism.py 断言）。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_SEED = 20260101

SURNAMES = ["张", "王", "李", "赵", "陈", "刘", "杨", "黄", "周", "吴",
            "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林", "罗"]
GIVEN_A = ["伟", "芳", "娜", "敏", "静", "强", "磊", "洋", "艳", "勇",
           "军", "杰", "娟", "涛", "明", "超", "秀", "霞", "平", "刚"]
GIVEN_B = ["", "华", "生", "力", "云", "天", "山", "石", "光", "峰",
           "文", "武", "清", "晨", "航", "宇", "宁", "安", "和", "顺"]
BRANDS = ["宏远", "汇泽", "嘉禾", "锦程", "启源", "海通", "正合", "铭泰",
          "环宇", "永昌", "博盛", "诚达", "远航", "天工", "中润", "晟丰",
          "华翔", "聚源", "津润", "新程", "立信", "众和", "兴盛", "德昌"]
INDUSTRY = ["建材", "智能科技", "商贸", "机械", "物流", "装饰", "电子", "供应链",
            "能源", "环保", "医疗器械", "食品", "纺织", "化工"]
SUFFIX = ["有限公司", "股份有限公司", "有限责任公司"]
TOPICS = ["会员开放日", "产业对接会", "财税合规讲座", "企业数字化工作坊",
          "供应链金融沙龙", "品牌出海研讨", "人力资源论坛", "政策解读会",
          "投融资路演", "园区企业走访"]
CHANNEL = ["电话", "上门", "微信", "邮件", "活动"]
MEMBER_STATUS_ALLOWED = ["active", "suspended", "expired"]
CC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
CC_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]

MEMBERS_COLS = ["member_id", "company_name", "credit_code", "member_status", "site_id",
                "contact_name", "contact_role", "mobile", "email", "created_at"]
CONTRACTS_COLS = ["contract_id", "member_id", "company_name", "credit_code", "amount_fen",
                  "sign_date", "start_date", "end_date", "status"]
LEASES_COLS = ["lease_id", "unit_id", "site_id", "member_id", "company_name", "area_sqm",
               "start_date", "end_date", "rent_fen", "renew_from", "status"]
UNITS_COLS = ["unit_id", "site_id", "unit_name", "area_sqm", "status"]
ACTIVITIES_COLS = ["session_id", "session_date", "topic", "attendee_name", "attendee_mobile",
                   "attendee_email", "checkin_at", "source"]
INTERACTIONS_COLS = ["interaction_id", "member_id", "company_name", "channel", "occurred_at", "content"]

CONTRACTS_PREAMBLE = [["合同台账导出（示例数据）"], [""]]
ACTIVITIES_BLANK_AFTER = 449
INTERACTIONS_BLANK_AFTER = 999


def cc_check_char(body17: str) -> str:
    total = sum(CC_CHARS.index(c) * w for c, w in zip(body17, CC_WEIGHTS))
    return CC_CHARS[(31 - total % 31) % 31]


def make_credit_code(rng: random.Random) -> str:
    body = "91" + "".join(rng.choice("0123456789") for _ in range(6))
    body += "".join(rng.choice(CC_CHARS) for _ in range(9))
    return body + cc_check_char(body)


def make_mobile(rng: random.Random) -> str:
    prefix = rng.choice(["130", "131", "133", "135", "136", "137", "138", "139",
                         "150", "151", "156", "158", "159", "180", "186", "188", "199"])
    return prefix + "0000" + "".join(rng.choice("0123456789") for _ in range(4))


def person_name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN_A) + rng.choice(GIVEN_B)


def row_of(idx: int, header_rows: int = 1, blanks_before: int = 0) -> int:
    """0 基数据下标 → 文件物理行号（1 基，含表头/标题行）。"""
    return idx + header_rows + blanks_before + 1


def _contact(seq: int, company: Dict[str, Any], primary: bool, rng: random.Random) -> Dict[str, Any]:
    return {
        "member_id": company["member_id"],
        "company_name": company["company_name"],
        "credit_code": company["credit_code"],
        "member_status": company["member_status"],
        "site_id": company["site_id"],
        "contact_name": person_name(rng),
        "contact_role": "主联系人" if primary else "联系人",
        "mobile": make_mobile(rng),
        "email": "user%03d@example.com" % seq,
        "created_at": company["joined_on"],
    }


def build_base(rng: random.Random):
    sites = ["site_%02d" % (i + 1) for i in range(6)]

    companies: List[Dict[str, Any]] = []
    used = set()
    for i in range(120):
        while True:
            name = "示例" + rng.choice(BRANDS) + rng.choice(INDUSTRY) + rng.choice(SUFFIX)
            if name not in used:
                used.add(name)
                break
        companies.append({
            "member_id": "M%04d" % (i + 1),
            "company_name": name,
            "credit_code": make_credit_code(rng),
            "member_status": "active" if i < 100 else ("suspended" if i % 2 else "expired"),
            "site_id": sites[i % len(sites)],
            "joined_on": (date(2023, 1, 1) + timedelta(days=rng.randrange(0, 700))).isoformat(),
        })

    contacts: List[Dict[str, Any]] = []
    seq = 0
    for c in companies:
        seq += 1
        contacts.append(_contact(seq, c, True, rng))
    for k in range(180):
        c = companies[k % len(companies)]
        seq += 1
        contacts.append(_contact(seq, c, False, rng))

    units = [{
        "unit_id": "U%04d" % (i + 1),
        "site_id": sites[i % len(sites)],
        "unit_name": "%s-%02d层-%02d号" % (sites[i % len(sites)], (i // 20) % 8 + 1, i % 20 + 1),
        "area_sqm": 60 + (i * 7) % 240,
        "status": rng.choice(["vacant", "leased", "reserved"]),
    } for i in range(180)]

    contracts: List[Dict[str, Any]] = []
    for i in range(160):
        c = companies[i % len(companies)]
        sign = date(2023, 1, 1) + timedelta(days=rng.randrange(0, 900))
        months = rng.choice([12, 24, 36])
        contracts.append({
            "contract_id": "C%04d" % (i + 1),
            "member_id": c["member_id"],
            "company_name": c["company_name"],
            "credit_code": c["credit_code"],
            "amount_fen": rng.choice([120000, 240000, 360000, 480000, 600000]) + rng.randrange(0, 100) * 100,
            "sign_date": sign.isoformat(),
            "start_date": sign.isoformat(),
            "end_date": (sign + timedelta(days=30 * months)).isoformat(),
            "status": rng.choice(["effective", "expired", "terminated"]),
        })

    leases: List[Dict[str, Any]] = []
    for i in range(140):
        u = units[i]
        c = companies[i % len(companies)]
        start = date(2024, 1, 1) + timedelta(days=rng.randrange(0, 120))
        months = rng.choice([6, 12, 24])
        leases.append({
            "lease_id": "L%04d" % (i + 1),
            "unit_id": u["unit_id"],
            "site_id": u["site_id"],
            "member_id": c["member_id"],
            "company_name": c["company_name"],
            "area_sqm": u["area_sqm"],
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=30 * months)).isoformat(),
            "rent_fen": 80000 + rng.randrange(0, 60) * 1000,
            "renew_from": "",
            "status": rng.choice(["active", "active", "active", "ended"]),
        })

    activities: List[Dict[str, Any]] = []
    for s in range(60):
        day = date(2024, 3, 1) + timedelta(days=s * 5)
        for p in rng.sample(range(len(contacts)), 15):
            ct = contacts[p]
            activities.append({
                "session_id": "S%03d" % (s + 1),
                "session_date": day.isoformat(),
                "topic": TOPICS[s % len(TOPICS)],
                "attendee_name": ct["contact_name"],
                "attendee_mobile": ct["mobile"],
                "attendee_email": ct["email"],
                "checkin_at": (datetime(2024, 3, 1, 9, 0) + timedelta(days=s * 5, minutes=rng.randrange(0, 180))).strftime("%Y-%m-%d %H:%M"),
                "source": rng.choice(["报名链接", "现场登记", "邀请"]),
            })

    interactions: List[Dict[str, Any]] = []
    for i in range(1500):
        c = companies[rng.randrange(len(companies))]
        ch = rng.choice(CHANNEL)
        ts = datetime(2024, 1, 1, 9, 0) + timedelta(minutes=rng.randrange(0, 60 * 24 * 200))
        interactions.append({
            "interaction_id": "I%05d" % (i + 1),
            "member_id": c["member_id"],
            "company_name": c["company_name"],
            "channel": ch,
            "occurred_at": ts.strftime("%Y-%m-%d %H:%M"),
            "content": "%s沟通：%s" % (ch, rng.choice(["咨询续租", "询问会员权益", "反馈场地空调",
                                                        "申请活动场地", "对接供应链资源", "了解招商政策",
                                                        "报名开放日", "投诉停车"])),
        })

    return companies, contacts, units, contracts, leases, activities, interactions


def build(seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    rng = random.Random(seed)
    companies, contacts, units, contracts, leases, activities, interactions = build_base(rng)
    # 名册输出用副本：脏数据只污染写出文件，不影响由干净联系人派生的活动记录
    members: List[Dict[str, Any]] = [dict(c) for c in contacts]
    defects: List[Dict[str, Any]] = []

    def note(code: str, file: str, rows: List[int], field: str, detail: str) -> None:
        defects.append({"code": code, "file": file, "rows": rows, "field": field, "detail": detail})

    def mrow(idx: int) -> int:
        return row_of(idx, 1)

    def crow(idx: int) -> int:
        return row_of(idx, 3)

    def lrow(idx: int) -> int:
        return row_of(idx, 1)

    def arow(idx: int) -> int:
        return row_of(idx, 1, 1 if idx > ACTIVITIES_BLANK_AFTER else 0)

    def irow(idx: int) -> int:
        return row_of(idx, 1, 1 if idx > INTERACTIONS_BLANK_AFTER else 0)

    # ---- members.csv ----
    for idx in (7, 88, 163, 251):
        members[idx]["contact_name"] += "ＡＢ"
        note("FULLWIDTH_CHAR", "members.csv", [mrow(idx)], "contact_name", "联系人姓名含全角英文字符")

    variants = ["138 0000 1234", "137-0000-5678", "+86 13900002468", " 13500001111",
                "(136)00009999", "150.0000.2222"]
    for idx, v in zip((11, 42, 129, 205, 264, 288), variants):
        members[idx]["mobile"] = v
        note("PHONE_FORMAT_VARIANT", "members.csv", [mrow(idx)], "mobile", "手机号非标准 11 位写法：%r" % v)

    for idx, v in zip((60, 174, 233), ("1.3800001234E+10", "1.3900005678E+10", "1.5100001111E+10")):
        members[idx]["mobile"] = v
        note("PHONE_SCIENTIFIC", "members.csv", [mrow(idx)], "mobile", "单元格被转成科学计数法：%s" % v)

    for idx in (181, 200, 222, 246, 275):
        cc = contacts[idx]["credit_code"]
        wrong = cc[:17] + ("0" if cc[17] != "0" else "1")
        members[idx]["credit_code"] = wrong
        note("CREDIT_CODE_CHECKSUM", "members.csv", [mrow(idx)], "credit_code", "校验位不符：%s → %s" % (cc, wrong))

    # 只落在非 active 企业（主联系人 idx≥100 / 副联系人 idx 220~239），避免改变 100 家 active 的口径
    for idx, v in zip((105, 118, 221, 228, 236), ["ACTIVE", "Active", "冻结", "pending", "active  "]):
        members[idx]["member_status"] = v
        note("UNKNOWN_ENUM", "members.csv", [mrow(idx)], "member_status", "非允许枚举值：%r" % v)

    members[33]["created_at"] = "2024/06/01"
    note("MIXED_DATE_FORMAT", "members.csv", [mrow(33)], "created_at", "斜杠日期 2024/06/01")
    members[158]["created_at"] = "2024.06.02"
    note("MIXED_DATE_FORMAT", "members.csv", [mrow(158)], "created_at", "点号日期 2024.06.02")

    # ---- contracts.csv ----
    note("TITLE_ROW", "contracts.csv", [1], "-", "表头之前多出一行标题：合同台账导出（示例数据）")
    note("BLANK_ROW", "contracts.csv", [2], "-", "标题行与表头之间的空白行")

    for src in (3, 31, 62, 97, 128):
        dup = dict(contracts[src])
        contracts.append(dup)
        note("DUPLICATE_ROW_IN_FILE", "contracts.csv", [crow(src), crow(len(contracts) - 1)], "整行",
             "与第 %d 行完全重复（contract_id=%s）" % (crow(src), dup["contract_id"]))

    for idx in (5, 19, 34, 48, 66, 79, 92, 105, 121, 137):
        orig = contracts[idx]["company_name"]
        short = orig.replace("有限责任公司", "有限公司").replace("股份有限公司", "公司").replace("有限公司", "公司")
        contracts[idx]["company_name"] = short
        note("CROSS_FILE_NAME_VARIANT", "contracts.csv", [crow(idx)], "company_name",
             "与名册不一致：%s（名册为 %s）" % (short, orig))

    for idx, v in zip((10, 55, 110), ("2024/07/01", "20240702", "2024.07.03")):
        contracts[idx]["sign_date"] = v
        note("MIXED_DATE_FORMAT", "contracts.csv", [crow(idx)], "sign_date", "非 ISO 日期：%s" % v)

    # ---- leases.xlsx ----
    for a, b in ((40, 41), (95, 96)):
        leases[b]["unit_id"] = leases[a]["unit_id"]
        leases[b]["site_id"] = leases[a]["site_id"]
        leases[b]["start_date"] = leases[a]["end_date"]
        note("LEASE_OVERLAP", "leases.xlsx", [lrow(a), lrow(b)], "start_date",
             "单元 %s 租期重叠（%s 止 / %s 起）" % (leases[a]["unit_id"], leases[a]["end_date"], leases[b]["start_date"]))

    leases[50]["renew_from"] = "L0053"
    leases[51]["renew_from"] = "L0051"
    leases[52]["renew_from"] = "L0052"
    note("RENEWAL_CYCLE", "leases.xlsx", [lrow(50), lrow(51), lrow(52)], "renew_from",
         "续签链成环：L0051→L0053→L0052→L0051")

    leases[70]["unit_id"] = leases[71]["unit_id"]
    leases[71]["site_id"] = "site_06" if leases[70]["site_id"] != "site_06" else "site_05"
    leases[71]["start_date"] = leases[70]["start_date"]
    leases[71]["end_date"] = leases[70]["end_date"]
    note("SITE_CONFLICT", "leases.xlsx", [lrow(70), lrow(71)], "site_id",
         "单元 %s 被两个场地同时占用（%s / %s）" % (leases[70]["unit_id"], leases[70]["site_id"], leases[71]["site_id"]))

    merge_ranges: List[Tuple[int, int]] = []
    for anchor, n in ((119, 2), (129, 3)):
        base = leases[anchor]
        for k in range(1, n):
            leases[anchor + k]["member_id"] = base["member_id"]
            leases[anchor + k]["company_name"] = ""
        merge_ranges.append((lrow(anchor), lrow(anchor + n - 1)))
        note("MERGED_CELL", "leases.xlsx", [lrow(anchor), lrow(anchor + n - 1)], "company_name",
             "企业名称列单元格合并：B%d:B%d" % (lrow(anchor), lrow(anchor + n - 1)))

    for idx, v in zip((20, 78, 133), ("2024/02/01", "20240202", "2024.02.03")):
        leases[idx]["start_date"] = v
        note("MIXED_DATE_FORMAT", "leases.xlsx", [lrow(idx)], "start_date", "非 ISO 日期：%s" % v)

    # ---- activities.csv ----
    for idx, nm, mob in ((12, "欧阳锋", "13100007777"), (333, "慕容复", "13200008888"), (701, "独孤求败", "13300009999")):
        activities[idx]["attendee_name"] = nm
        activities[idx]["attendee_mobile"] = mob
        activities[idx]["attendee_email"] = "ghost%d@example.net" % idx
        note("UNMATCHED_ATTENDEE", "activities.csv", [arow(idx)], "attendee_mobile",
             "参与人不在名册：%s / %s" % (nm, mob))

    activities[222]["session_date"] = "2024/05/01"
    note("MIXED_DATE_FORMAT", "activities.csv", [arow(222)], "session_date", "非 ISO 日期：2024/05/01")
    note("BLANK_ROW", "activities.csv", [row_of(ACTIVITIES_BLANK_AFTER, 1) + 1], "-", "数据区中间的空行")

    # ---- interactions.csv ----
    for idx, mid in ((58, "M9001"), (404, "M9002"), (777, "M9003"), (1310, "M9004")):
        interactions[idx]["member_id"] = mid
        note("ORPHAN_INTERACTION", "interactions.csv", [irow(idx)], "member_id", "会员号不在名册：%s" % mid)

    for idx, idno in ((100, "110101199003071234"), (356, "310101198512123456"),
                      (612, "440301199201019876"), (906, "510101198808082345"), (1240, "330101199509095432")):
        interactions[idx]["content"] += "，客户留了证件号 " + idno
        note("ID_NUMBER_IN_BODY", "interactions.csv", [irow(idx)], "content", "自由文本含 18 位证件号：%s" % idno)

    note("BLANK_ROW", "interactions.csv", [row_of(INTERACTIONS_BLANK_AFTER, 1) + 1], "-", "数据区中间的空行")

    counts: Dict[str, int] = {}
    for d in defects:
        counts[d["code"]] = counts.get(d["code"], 0) + 1

    return {
        "seed": seed,
        "members": members,
        "contracts": contracts,
        "leases": leases,
        "units": units,
        "activities": activities,
        "interactions": interactions,
        "merge_ranges": merge_ranges,
        "defects": defects,
        "counts": dict(sorted(counts.items())),
    }


def write_csv(path: str, rows: List[Dict[str, Any]], cols: List[str], encoding: str = "utf-8",
              preamble: Optional[List[List[str]]] = None, blank_after: Optional[int] = None) -> None:
    with open(path, "w", encoding=encoding, newline="") as f:
        w = csv.writer(f)
        for pre in preamble or []:
            w.writerow(pre)
        w.writerow(cols)
        for i, r in enumerate(rows):
            w.writerow([r.get(c, "") for c in cols])
            if blank_after is not None and i == blank_after:
                w.writerow([""] * len(cols))


def write_xlsx(path: str, rows: List[Dict[str, Any]], cols: List[str],
               merge_ranges: List[Tuple[int, int]], name_col: str = "company_name") -> None:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "leases"
    ws.append(cols)
    name_idx = cols.index(name_col) + 1
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    for start, end in merge_ranges:
        ws.merge_cells(start_row=start, start_column=name_idx, end_row=end, end_column=name_idx)
    wb.save(path)


def write_all(data: Dict[str, Any], out: str) -> List[str]:
    os.makedirs(out, exist_ok=True)
    p = lambda n: os.path.join(out, n)  # noqa: E731
    write_csv(p("members.csv"), data["members"], MEMBERS_COLS)
    write_csv(p("contracts.csv"), data["contracts"], CONTRACTS_COLS, preamble=CONTRACTS_PREAMBLE)
    write_xlsx(p("leases.xlsx"), data["leases"], LEASES_COLS, data["merge_ranges"])
    write_csv(p("unit_inventory.csv"), data["units"], UNITS_COLS)
    write_csv(p("activities.csv"), data["activities"], ACTIVITIES_COLS, blank_after=ACTIVITIES_BLANK_AFTER)
    write_csv(p("interactions.csv"), data["interactions"], INTERACTIONS_COLS,
              encoding="gb18030", blank_after=INTERACTIONS_BLANK_AFTER)
    answer = {
        "seed": data["seed"],
        "files": {
            "members": "members.csv",
            "contracts": "contracts.csv",
            "leases": "leases.xlsx",
            "units": "unit_inventory.csv",
            "activities": "activities.csv",
            "interactions": "interactions.csv",
        },
        "row_convention": "文件物理行号（1 基，含表头与标题行）",
        "counts": data["counts"],
        "total": len(data["defects"]),
        "defects": data["defects"],
    }
    with open(p("answer_key.json"), "w", encoding="utf-8") as f:
        json.dump(answer, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return [p(n) for n in ("members.csv", "contracts.csv", "leases.xlsx", "unit_inventory.csv",
                           "activities.csv", "interactions.csv", "answer_key.json")]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="五类来源虚构样例数据生成器")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", default="samples")
    args = ap.parse_args(argv)
    data = build(args.seed)
    files = write_all(data, args.out)
    print("seed=%d 文件=%d 预埋缺陷=%d 类型=%d" % (args.seed, len(files), len(data["defects"]), len(data["counts"])))
    for k, v in data["counts"].items():
        print("  %-24s %d" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())

