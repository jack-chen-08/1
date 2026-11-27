# -*- coding: utf-8 -*-
"""合同台账映射器：标题行/空白行、重复行、跨文件企业名称变体、日期格式。"""
from __future__ import annotations

from typing import Dict, List, Tuple

from . import base


def load(path: str) -> Tuple[List[Tuple[int, Dict[str, str]]], List[base.Issue]]:
    _, rows, struct_issues = base.read_csv(path, expect_first_col="contract_id")
    return rows, struct_issues


def validate(path: str, companies: Dict[str, Dict[str, str]], file: str = "contracts.csv") -> List[base.Issue]:
    rows, issues = load(path)
    issues += base.check_duplicates(file, rows)
    for rn, row in rows:
        mid = (row.get("member_id") or "").strip()
        name = (row.get("company_name") or "").strip()
        master = companies.get(mid)
        if master and name and name != master["company_name"]:
            issues.append(base.make("CROSS_FILE_NAME_VARIANT", file, [rn], "company_name",
                                    "台账为「%s」，名册为「%s」" % (name, master["company_name"])))
    for col in ("sign_date", "start_date", "end_date"):
        issues += base.check_iso_date(file, rows, col)
    return issues
