# -*- coding: utf-8 -*-
"""AC2 答案文件与 README 清单一致；AC4 映射器逐条命中且无误报。"""
from __future__ import annotations

import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mappers  # noqa: E402


def _readme_counts() -> dict:
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        text = f.read()
    block = text.split("## 4. 预埋缺陷清单", 1)[1].split("## 5.", 1)[0]
    counts = {}
    for line in block.splitlines():
        m = re.match(r"^\|\s*`([A-Z_]+)`\s*\|[^|]*\|\s*(\d+)\s*\|", line)
        if m:
            counts[m.group(1)] = int(m.group(2))
    return counts


def test_readme_counts_match_answer_key(samples):
    """AC2：README 清单逐项 == answer_key.counts，且总数一致。"""
    _, data = samples
    readme = _readme_counts()
    assert readme, "README 未解析到缺陷清单表"
    assert readme == data["counts"], "README=%s / answer_key=%s" % (readme, data["counts"])
    assert sum(readme.values()) == len(data["defects"])


def test_every_defect_has_row_and_field(samples):
    """答案文件结构完整：每条都有文件、行号、字段、说明。"""
    _, data = samples
    for d in data["defects"]:
        assert d["file"] and d["rows"] and d["field"] and d["detail"], d


def test_ac4_mappers_hit_all_and_no_false_positive(samples):
    """AC4：映射器预演，答案文件中的缺陷全部检出，且无额外误报。"""
    folder, data = samples
    detected = [i.as_dict() for i in mappers.run_all(folder)]
    exp = sorted((d["code"], d["file"], tuple(sorted(d["rows"]))) for d in data["defects"])
    got = sorted((d["code"], d["file"], tuple(sorted(d["rows"]))) for d in detected)
    assert sorted(set(exp) - set(got)) == [], "漏检"
    assert sorted(set(got) - set(exp)) == [], "误报"
    assert len(got) == len(exp) == 69


def test_error_level_issues_only_in_answer_key(samples):
    """干净行不产生 error：所有 error 级问题都必须出现在答案文件里。"""
    folder, data = samples
    answer = {(d["code"], d["file"], tuple(sorted(d["rows"]))) for d in data["defects"]}
    for issue in mappers.run_all(folder):
        if issue.severity == "error":
            assert issue.key() in answer, "未登记的 error：%s" % (issue.as_dict(),)
