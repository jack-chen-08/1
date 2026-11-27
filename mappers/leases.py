# -*- coding: utf-8 -*-
"""租约台账映射器：合并单元格、租期重叠、续签成环、场地冲突、日期格式。"""
from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from . import base

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


def load(path: str) -> Tuple[List[Tuple[int, Dict[str, str]]], List[base.Issue], List[Tuple[int, int]]]:
    _, rows, struct_issues, merges = base.read_xlsx(path)
    return rows, struct_issues, merges


def validate(path: str, file: str = "leases.xlsx") -> List[base.Issue]:
    rows, issues, merges = load(path)
    rows = [(rn, r) for rn, r in rows if (r.get("lease_id") or "").strip()]
    by_row = dict(rows)

    # 合并单元格：企业名称列若被合并，同组行只有首行有值
    for start, end in merges:
        if end > start:
            issues.append(base.make("MERGED_CELL", file, [start, end], "company_name",
                                    "单元格合并区间：第 %d-%d 行" % (start, end)))

    # 日期格式
    for col in ("start_date", "end_date"):
        issues += base.check_iso_date(file, rows, col)

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
                issues.append(base.make("LEASE_OVERLAP", file, [rn1, rn2], "start_date",
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
                    issues.append(base.make("SITE_CONFLICT", file, sorted([rn1, rn2]), "site_id",
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
                issues.append(base.make("RENEWAL_CYCLE", file, sorted(row_of_lease[x] for x in cycle),
                                        "renew_from", "续签链成环：%s" % " → ".join(cycle + [nxt])))
                break
            cur = nxt
    return issues
