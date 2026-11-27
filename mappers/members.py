# -*- coding: utf-8 -*-
"""会员名册映射器：名册 → 企业（去重）+ 联系人。"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from . import base


def load(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], List[base.Issue]]:
    """返回（联系人列表、{member_id: 企业}、结构问题）。"""
    _, rows, struct_issues = base.read_csv(path, expect_first_col="member_id")
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


def validate(path: str) -> List[base.Issue]:
    contacts, _, issues = load(path)
    f = "members.csv"
    issues += base.check_fullwidth(f, [(c["_row"], c) for c in contacts])
    issues += base.check_mobile(f, [(c["_row"], c) for c in contacts])
    issues += base.check_credit_code(f, [(c["_row"], c) for c in contacts])
    issues += base.check_enum(f, [(c["_row"], c) for c in contacts], "member_status", base.MEMBER_STATUS_ALLOWED)
    issues += base.check_iso_date(f, [(c["_row"], c) for c in contacts], "created_at")
    return issues
