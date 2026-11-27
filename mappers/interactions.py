# -*- coding: utf-8 -*-
"""互动记录映射器：孤儿互动、正文证件号、空白行。"""
from __future__ import annotations

from typing import Dict, List, Set, Tuple

from . import base


def load(path: str) -> Tuple[List[Tuple[int, Dict[str, str]]], List[base.Issue]]:
    _, rows, struct_issues = base.read_csv(path, encoding="gb18030", expect_first_col="interaction_id")
    return rows, struct_issues


def validate(path: str, master_ids: Set[str], file: str = "interactions.csv") -> List[base.Issue]:
    rows, issues = load(path)
    for rn, r in rows:
        mid = (r.get("member_id") or "").strip()
        if mid not in master_ids:
            issues.append(base.make("ORPHAN_INTERACTION", file, [rn], "member_id",
                                    "会员号不在名册：%s" % mid))
        content = r.get("content") or ""
        for m in base.RE_ID_CARD.finditer(content):
            issues.append(base.make("ID_NUMBER_IN_BODY", file, [rn], "content",
                                    "正文含 18 位证件号：%s" % m.group(0)))
            break
    return issues
