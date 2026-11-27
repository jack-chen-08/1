# -*- coding: utf-8 -*-
"""五类来源映射器（单文件版）—— members / contracts / leases / activities / interactions。

对外只暴露四个名字：Issue、master_sets、run_all，以及五个 validate_* 函数。
每个 validate_* 返回 List[Issue]；run_all(samples_dir) 一次跑完五类并汇总。
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple



# ===========================================================================
# 公共件：Issue / 读取 / 通用校验
# ===========================================================================
# -*- coding: utf-8 -*-
"""映射器公共件：问题对象、CSV/XLSX 读取、通用校验规则。"""

from dataclasses import dataclass, field

CC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
CC_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]
MEMBER_STATUS_ALLOWED = {"active", "suspended", "expired"}

RE_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_MOBILE = re.compile(r"^1[3-9]\d{9}$")
RE_SCIENTIFIC = re.compile(r"^[+-]?\d(?:\.\d+)?[eE][+-]?\d+$")
RE_FULLWIDTH = re.compile(r"[\u3000\uff01-\uff5e]")
RE_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

SEVERITY = {"TITLE_ROW": "warning", "BLANK_ROW": "warning", "MERGED_CELL": "warning"}


@dataclass(frozen=True)
class Issue:
    code: str
    file: str
    rows: Tuple[int, ...]
    field: str = "-"
    detail: str = ""
    severity: str = "error"

    def key(self) -> Tuple[str, str, Tuple[int, ...]]:
        return (self.code, self.file, self.rows)

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "file": self.file, "rows": list(self.rows),
                "field": self.field, "detail": self.detail, "severity": self.severity}


def make(code: str, file: str, rows: Sequence[int], field: str = "-", detail: str = "") -> Issue:
    return Issue(code, file, tuple(int(r) for r in rows), field, detail, SEVERITY.get(code, "error"))


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def read_csv(path: str, encoding: str = "utf-8", expect_first_col: Optional[str] = None
             ) -> Tuple[List[str], List[Tuple[int, Dict[str, str]]], List[Issue]]:
    """返回（表头、[(物理行号, 行字典)]、结构问题）。自动识别标题行与空白行。"""
    issues: List[Issue] = []
    with open(path, "r", encoding=encoding, newline="") as f:
        raw = list(csv.reader(f))

    header_idx = None
    for i, row in enumerate(raw):
        if expect_first_col and row and row[0].strip() == expect_first_col:
            header_idx = i
            break
    if header_idx is None:
        header_idx = 0
        while header_idx < len(raw) and not any(c.strip() for c in raw[header_idx]):
            header_idx += 1

    # 表头之前的行：非空 = 标题行，空 = 空白行
    for i in range(header_idx):
        row = raw[i]
        if any(c.strip() for c in row):
            issues.append(make("TITLE_ROW", _base(path), [i + 1], "-", "表头之前多出标题行：%s" % " ".join(c for c in row if c.strip())))
        else:
            issues.append(make("BLANK_ROW", _base(path), [i + 1], "-", "表头之前的空白行"))

    header = [h.strip() for h in raw[header_idx]]
    rows: List[Tuple[int, Dict[str, str]]] = []
    for i in range(header_idx + 1, len(raw)):
        row = raw[i]
        if not any(c.strip() for c in row):
            issues.append(make("BLANK_ROW", _base(path), [i + 1], "-", "数据区空白行"))
            continue
        rows.append((i + 1, {header[j]: (row[j] if j < len(row) else "") for j in range(len(header))}))
    return header, rows, issues


def read_xlsx(path: str) -> Tuple[List[str], List[Tuple[int, Dict[str, str]]], List[Issue], List[Tuple[int, int]]]:
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    issues: List[Issue] = []
    grid = [[("" if c is None else str(c)) for c in row] for row in ws.iter_rows(values_only=True)]
    header_idx = 0
    for i, row in enumerate(grid):
        if row and row[0].strip() == "lease_id":
            header_idx = i
            break
    for i in range(header_idx):
        if any(c.strip() for c in grid[i]):
            issues.append(make("TITLE_ROW", _base(path), [i + 1], "-", "表头之前多出标题行"))
        else:
            issues.append(make("BLANK_ROW", _base(path), [i + 1], "-", "表头之前的空白行"))
    header = [h.strip() for h in grid[header_idx]]
    rows: List[Tuple[int, Dict[str, str]]] = []
    for i in range(header_idx + 1, len(grid)):
        row = grid[i]
        if not any(c.strip() for c in row):
            issues.append(make("BLANK_ROW", _base(path), [i + 1], "-", "数据区空白行"))
            continue
        rows.append((i + 1, {header[j]: (row[j] if j < len(row) else "") for j in range(len(header))}))
    merges = [(r.min_row, r.max_row) for r in ws.merged_cells.ranges]
    return header, rows, issues, merges


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# 通用校验
# ---------------------------------------------------------------------------
def check_fullwidth(file: str, rows: List[Tuple[int, Dict[str, str]]]) -> List[Issue]:
    out = []
    for rn, row in rows:
        for col, val in row.items():
            if isinstance(val, str) and RE_FULLWIDTH.search(val):
                out.append(make("FULLWIDTH_CHAR", file, [rn], col, "含全角字符：%r" % val))
    return out


def check_mobile(file: str, rows: List[Tuple[int, Dict[str, str]]], col: str = "mobile") -> List[Issue]:
    out = []
    for rn, row in rows:
        val = row.get(col) or ""
        if not val:
            continue
        if RE_SCIENTIFIC.match(val):
            out.append(make("PHONE_SCIENTIFIC", file, [rn], col, "科学计数法：%s" % val))
        elif not RE_MOBILE.match(val):
            out.append(make("PHONE_FORMAT_VARIANT", file, [rn], col, "非标准 11 位：%r" % val))
    return out


def cc_check_char(body17: str) -> str:
    total = sum(CC_CHARS.index(c) * w for c, w in zip(body17, CC_WEIGHTS))
    return CC_CHARS[(31 - total % 31) % 31]


def check_credit_code(file: str, rows: List[Tuple[int, Dict[str, str]]], col: str = "credit_code") -> List[Issue]:
    out = []
    for rn, row in rows:
        val = (row.get(col) or "").strip().upper()
        if len(val) != 18 or any(c not in CC_CHARS for c in val):
            out.append(make("CREDIT_CODE_CHECKSUM", file, [rn], col, "长度或字符集非法：%s" % val))
            continue
        if cc_check_char(val[:17]) != val[17]:
            out.append(make("CREDIT_CODE_CHECKSUM", file, [rn], col, "校验位应为 %s，实为 %s" % (cc_check_char(val[:17]), val[17])))
    return out


def check_enum(file: str, rows: List[Tuple[int, Dict[str, str]]], col: str,
               allowed: Iterable[str]) -> List[Issue]:
    allowed = set(allowed)
    out = []
    for rn, row in rows:
        val = (row.get(col) or "")
        if val not in allowed:
            out.append(make("UNKNOWN_ENUM", file, [rn], col, "非允许枚举值：%r" % val))
    return out


def check_iso_date(file: str, rows: List[Tuple[int, Dict[str, str]]], col: str) -> List[Issue]:
    out = []
    for rn, row in rows:
        val = (row.get(col) or "").strip()
        if val and not RE_ISO_DATE.match(val):
            out.append(make("MIXED_DATE_FORMAT", file, [rn], col, "非 ISO 日期：%r" % val))
    return out


def check_duplicates(file: str, rows: List[Tuple[int, Dict[str, str]]]) -> List[Issue]:
    seen: Dict[Tuple[str, ...], List[int]] = {}
    for rn, row in rows:
        key = tuple(sorted((k, str(v)) for k, v in row.items()))
        seen.setdefault(key, []).append(rn)
    out = []
    for key, rns in seen.items():
        if len(rns) > 1:
            out.append(make("DUPLICATE_ROW_IN_FILE", file, sorted(rns), "整行",
                            "%d 行内容完全相同" % len(rns)))
    return out

# ===========================================================================
# members.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""会员名册映射器：名册 → 企业（去重）+ 联系人。"""




def load_members(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], List[Issue]]:
    """返回（联系人列表、{member_id: 企业}、结构问题）。"""
    _, rows, struct_issues = read_csv(path, expect_first_col="member_id")
    contacts: List[Dict[str, Any]] = []
    companies: Dict[str, Dict[str, Any]] = {}
    for rn, row in rows:
        row = dict(row)
        row["_row"] = rn
        contacts.append(row)
        mid = row.get("member_id", "")
        if mid and mid not in companies:
            companies[mid] = {
                "member_id": mid,
                "company_name": row.get("company_name", ""),
                "credit_code": row.get("credit_code", ""),
                "member_status": row.get("member_status", ""),
                "site_id": row.get("site_id", ""),
            }
    return contacts, companies, struct_issues


def validate_members(path: str) -> List[Issue]:
    contacts, _, issues = load_members(path)
    f = "members.csv"
    issues += check_fullwidth(f, [(c["_row"], c) for c in contacts])
    issues += check_mobile(f, [(c["_row"], c) for c in contacts])
    issues += check_credit_code(f, [(c["_row"], c) for c in contacts])
    issues += check_enum(f, [(c["_row"], c) for c in contacts], "member_status", MEMBER_STATUS_ALLOWED)
    issues += check_iso_date(f, [(c["_row"], c) for c in contacts], "created_at")
    return issues

# ===========================================================================
# contracts.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""合同台账映射器：标题行/空白行、重复行、跨文件企业名称变体、日期格式。"""




def load_contracts(path: str) -> Tuple[List[Tuple[int, Dict[str, str]]], List[Issue]]:
    _, rows, struct_issues = read_csv(path, expect_first_col="contract_id")
    return rows, struct_issues


def validate_contracts(path: str, companies: Dict[str, Dict[str, str]], file: str = "contracts.csv") -> List[Issue]:
    rows, issues = load_contracts(path)
    issues += check_duplicates(file, rows)
    for rn, row in rows:
        mid = (row.get("member_id") or "").strip()
        name = (row.get("company_name") or "").strip()
        master = companies.get(mid)
        if master and name and name != master["company_name"]:
            issues.append(make("CROSS_FILE_NAME_VARIANT", file, [rn], "company_name",
                                    "台账为「%s」，名册为「%s」" % (name, master["company_name"])))
    for col in ("sign_date", "start_date", "end_date"):
        issues += check_iso_date(file, rows, col)
    return issues

# ===========================================================================
# leases.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""租约台账映射器：合并单元格、租期重叠、续签成环、场地冲突、日期格式。"""



_RE_DATE = re.compile(r"^(\d{4})[-/.年]?(\d{1,2})[-/.月]?(\d{1,2})日?$")


def parse_date(text: str) -> Optional[date]:
    """宽容解析（ISO / 斜杠 / 点号 / 8 位紧凑），解析失败返回 None。"""
    s = (text or "").strip()
    m = _RE_DATE.match(s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def load_leases(path: str) -> Tuple[List[Tuple[int, Dict[str, str]]], List[Issue], List[Tuple[int, int]]]:
    _, rows, struct_issues, merges = read_xlsx(path)
    return rows, struct_issues, merges


def validate_leases(path: str, file: str = "leases.xlsx") -> List[Issue]:
    rows, issues, merges = load_leases(path)
    rows = [(rn, r) for rn, r in rows if (r.get("lease_id") or "").strip()]
    by_row = dict(rows)

    # 合并单元格：企业名称列若被合并，同组行只有首行有值
    for start, end in merges:
        if end > start:
            issues.append(make("MERGED_CELL", file, [start, end], "company_name",
                                    "单元格合并区间：第 %d-%d 行" % (start, end)))

    # 日期格式
    for col in ("start_date", "end_date"):
        issues += check_iso_date(file, rows, col)

    # 租期重叠：同单元、同场地、区间相交（首尾相接视为重叠）
    groups: Dict[Tuple[str, str], List[Tuple[int, date, date]]] = {}
    for rn, r in rows:
        s, e = parse_date(r.get("start_date", "")), parse_date(r.get("end_date", ""))
        if not s or not e:
            continue
        key = ((r.get("unit_id") or "").strip(), (r.get("site_id") or "").strip())
        groups.setdefault(key, []).append((rn, s, e))
    for key, items in sorted(groups.items()):
        items.sort(key=lambda x: (x[1], x[0]))
        for i in range(len(items) - 1):
            rn1, s1, e1 = items[i]
            rn2, s2, e2 = items[i + 1]
            if s2 <= e1:
                issues.append(make("LEASE_OVERLAP", file, [rn1, rn2], "start_date",
                                        "单元 %s（%s）租期重叠：%s~%s 与 %s~%s" % (
                                            key[0], key[1], s1, e1, s2, e2)))

    # 场地冲突：同一单元被不同场地同时占用
    by_unit: Dict[str, List[Tuple[int, str, date, date]]] = {}
    for rn, r in rows:
        s, e = parse_date(r.get("start_date", "")), parse_date(r.get("end_date", ""))
        if not s or not e:
            continue
        by_unit.setdefault((r.get("unit_id") or "").strip(), []).append(
            (rn, (r.get("site_id") or "").strip(), s, e))
    for unit, items in sorted(by_unit.items()):
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                rn1, site1, s1, e1 = items[i]
                rn2, site2, s2, e2 = items[j]
                if site1 != site2 and s2 <= e1 and s1 <= e2:
                    issues.append(make("SITE_CONFLICT", file, sorted([rn1, rn2]), "site_id",
                                            "单元 %s 同时被 %s 与 %s 占用" % (unit, site1, site2)))

    # 续签链成环
    chain: Dict[str, str] = {}
    row_of_lease: Dict[str, int] = {}
    for rn, r in rows:
        lid = (r.get("lease_id") or "").strip()
        row_of_lease[lid] = rn
        rf = (r.get("renew_from") or "").strip()
        if rf:
            chain[lid] = rf
    visited: Dict[str, int] = {}
    for start_id in sorted(chain):
        path: List[str] = []
        cur = start_id
        while cur in chain and cur not in visited:
            visited[cur] = 1
            path.append(cur)
            nxt = chain[cur]
            if nxt in path:
                cycle = path[path.index(nxt):]
                issues.append(make("RENEWAL_CYCLE", file, sorted(row_of_lease[x] for x in cycle),
                                        "renew_from", "续签链成环：%s" % " → ".join(cycle + [nxt])))
                break
            cur = nxt
    return issues

# ===========================================================================
# activities.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""活动记录映射器：未匹配参与人、日期格式、空白行。"""




def load_activities(path: str) -> Tuple[List[Tuple[int, Dict[str, str]]], List[Issue]]:
    _, rows, struct_issues = read_csv(path, expect_first_col="record_type")
    return rows, struct_issues


def validate_activities(path: str, master_emails: Set[str], master_pairs: Set[Tuple[str, str]],
             file: str = "activities.csv") -> List[Issue]:
    rows, issues = load_activities(path)
    for rn, r in rows:
        # 场次形态行（record_type=session）没有人，跳过参与人匹配；参与人形态行才校验
        if (r.get("record_type") or "").strip() == "session":
            continue
        email = (r.get("attendee_email") or "").strip().lower()
        pair = ((r.get("attendee_name") or "").strip(), (r.get("attendee_mobile") or "").strip())
        if email in master_emails or pair in master_pairs:
            continue
        issues.append(make("UNMATCHED_ATTENDEE", file, [rn], "attendee_mobile",
                                "参与人不在名册：%s / %s" % (pair[0], pair[1])))
    issues += check_iso_date(file, rows, "session_date")
    return issues

# ===========================================================================
# interactions.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""互动记录映射器：孤儿互动、正文证件号、空白行。"""




def load_interactions(path: str) -> Tuple[List[Tuple[int, Dict[str, str]]], List[Issue]]:
    _, rows, struct_issues = read_csv(path, encoding="gb18030", expect_first_col="interaction_id")
    return rows, struct_issues


def validate_interactions(path: str, master_ids: Set[str], file: str = "interactions.csv") -> List[Issue]:
    rows, issues = load_interactions(path)
    for rn, r in rows:
        mid = (r.get("member_id") or "").strip()
        if mid not in master_ids:
            issues.append(make("ORPHAN_INTERACTION", file, [rn], "member_id",
                                    "会员号不在名册：%s" % mid))
        content = r.get("content") or ""
        for m in RE_ID_CARD.finditer(content):
            issues.append(make("ID_NUMBER_IN_BODY", file, [rn], "content",
                                    "正文含 18 位证件号：%s" % m.group(0)))
            break
    return issues


# ===========================================================================
# 统一入口
# ===========================================================================
def master_sets(members_path: str) -> Tuple[Dict[str, Dict[str, Any]], Set[str], Set[Tuple[str, str]]]:
    contacts, companies, _ = load_members(members_path)
    emails = {(c.get("email") or "").strip().lower() for c in contacts}
    pairs = {((c.get("contact_name") or "").strip(), (c.get("mobile") or "").strip()) for c in contacts}
    return companies, emails, pairs


def run_all(samples_dir: str) -> List[Issue]:
    p = lambda n: os.path.join(samples_dir, n)  # noqa: E731
    companies, emails, pairs = master_sets(p("members.csv"))
    issues: List[Issue] = []
    issues += validate_members(p("members.csv"))
    issues += validate_contracts(p("contracts.csv"), companies)
    issues += validate_leases(p("leases.xlsx"))
    issues += validate_activities(p("activities.csv"), emails, pairs)
    issues += validate_interactions(p("interactions.csv"), set(companies))
    return issues

