# -*- coding: utf-8 -*-
"""活动记录映射器：未匹配参与人、日期格式、空白行。"""
from __future__ import annotations

from typing import Dict, List, Set, Tuple

from . import base


def load(path: str) -> Tuple[List[Tuple[int, Dict[str, str]]], List[base.Issue]]:
    _, rows, struct_issues = base.read_csv(path, expect_first_col="session_id")
    return rows, struct_issues


def validate(path: str, master_emails: Set[str], master_pairs: Set[Tuple[str, str]],
             file: str = "activities.csv") -> List[base.Issue]:
    rows, issues = load(path)
    for rn, r in rows:
        email = (r.get("attendee_email") or "").strip().lower()
        pair = ((r.get("attendee_name") or "").strip(), (r.get("attendee_mobile") or "").strip())
        if email in master_emails or pair in master_pairs:
            continue
        issues.append(base.make("UNMATCHED_ATTENDEE", file, [rn], "attendee_mobile",
                                "参与人不在名册：%s / %s" % (pair[0], pair[1])))
    issues += base.check_iso_date(file, rows, "session_date")
    return issues
