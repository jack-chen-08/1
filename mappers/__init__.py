# -*- coding: utf-8 -*-
"""五类来源映射器：统一入口 run_all(samples_dir) → 问题清单。"""
from __future__ import annotations

import os
from typing import Dict, List, Set, Tuple

from . import base, members, contracts, leases, activities, interactions  # noqa: F401
from .base import Issue

__all__ = ["Issue", "run_all", "master_sets", "members", "contracts", "leases", "activities", "interactions"]


def master_sets(members_path: str) -> Tuple[Dict[str, Dict[str, str]], Set[str], Set[Tuple[str, str]]]:
    contacts, companies, _ = members.load(members_path)
    emails = {(c.get("email") or "").strip().lower() for c in contacts}
    pairs = {((c.get("contact_name") or "").strip(), (c.get("mobile") or "").strip()) for c in contacts}
    return companies, emails, pairs


def run_all(samples_dir: str) -> List[Issue]:
    p = lambda n: os.path.join(samples_dir, n)  # noqa: E731
    companies, emails, pairs = master_sets(p("members.csv"))
    issues: List[Issue] = []
    issues += members.validate(p("members.csv"))
    issues += contracts.validate(p("contracts.csv"), companies)
    issues += leases.validate(p("leases.xlsx"))
    issues += activities.validate(p("activities.csv"), emails, pairs)
    issues += interactions.validate(p("interactions.csv"), set(companies))
    return issues
