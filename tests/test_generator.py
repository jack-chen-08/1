# -*- coding: utf-8 -*-
"""AC1 确定性、AC3 虚构规则、数据体量断言。"""
from __future__ import annotations

import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gen_import_samples as gen  # noqa: E402


def _csv_cells(path, encoding="utf-8"):
    with open(path, encoding=encoding, newline="") as f:
        return [tuple(r) for r in csv.reader(f)]


def _xlsx_cells(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    return [tuple("" if c is None else str(c) for c in row) for row in ws.iter_rows(values_only=True)]


def _snapshot(folder):
    snap = {}
    for name in ("members.csv", "contracts.csv", "unit_inventory.csv", "activities.csv"):
        snap[name] = _csv_cells(os.path.join(folder, name))
    snap["interactions.csv"] = _csv_cells(os.path.join(folder, "interactions.csv"), "gb18030")
    snap["leases.xlsx"] = _xlsx_cells(os.path.join(folder, "leases.xlsx"))
    with open(os.path.join(folder, "answer_key.json"), encoding="utf-8") as f:
        snap["answer_key.json"] = json.load(f)
    return snap


def test_ac1_same_seed_identical_cells(tmp_path):
    """AC1：同一 seed 两次运行，所有单元格值与答案文件逐格一致。"""
    a, b = tmp_path / "a", tmp_path / "b"
    gen.write_all(gen.build(gen.DEFAULT_SEED), str(a))
    gen.write_all(gen.build(gen.DEFAULT_SEED), str(b))
    snap_a, snap_b = _snapshot(str(a)), _snapshot(str(b))
    assert set(snap_a) == set(snap_b)
    for name in snap_a:
        assert snap_a[name] == snap_b[name], "文件不一致：%s" % name


def test_ac1_different_seed_differs(tmp_path):
    """反证：不同 seed 必须产出不同数据，证明 seed 真的起作用。"""
    a, b = tmp_path / "a", tmp_path / "b"
    gen.write_all(gen.build(gen.DEFAULT_SEED), str(a))
    gen.write_all(gen.build(gen.DEFAULT_SEED + 1), str(b))
    assert _snapshot(str(a))["members.csv"] != _snapshot(str(b))["members.csv"]


def test_ac3_company_names_all_fiction(samples):
    """AC3：企业名 100% 含「示例」字样，且不含真实企业常见后缀组合以外的非虚构标识。"""
    folder, _ = samples
    with open(os.path.join(folder, "members.csv"), encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    names = {r["company_name"] for r in rows}
    assert len(names) == 120
    assert all("示例" in n for n in names), [n for n in names if "示例" not in n]


def test_ac3_mobile_mid_four_zeros(samples):
    """AC3：非缺陷行手机号中间 4 位为 0000（缺陷行由 answer_key 显式声明）。"""
    folder, data = samples
    bad_rows = {d["rows"][0] for d in data["defects"]
                if d["code"] in ("PHONE_FORMAT_VARIANT", "PHONE_SCIENTIFIC") and d["file"] == "members.csv"}
    with open(os.path.join(folder, "members.csv"), encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    pat = re.compile(r"^1[3-9]\d0000\d{4}$")
    for i, r in enumerate(rows, start=2):
        if i in bad_rows:
            continue
        assert pat.match(r["mobile"]), "第 %d 行手机号 %r 不符虚构规则" % (i, r["mobile"])


def test_ac3_emails_fiction_domain(samples):
    folder, _ = samples
    with open(os.path.join(folder, "members.csv"), encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert all(r["email"].endswith("@example.com") for r in rows)


def test_volume(samples):
    """体量断言：名册 120 企业/300 联系人（100 active）、合同 160、租约 140、单元 180、活动 900/60 场、互动 1500。"""
    folder, data = samples
    assert len(data["members"]) == 300
    assert len({c["member_id"] for c in data["members"]}) == 120
    companies: dict = {}
    for c in data["members"]:
        prev = companies.get(c["member_id"])
        if prev is None or prev != "active":
            companies[c["member_id"]] = c["member_status"]
    active = {mid for mid, st in companies.items() if st == "active"}
    assert len(active) == 100, "active 企业数应为 100，实为 %d" % len(active)
    assert len(data["contracts"]) == 165  # 160 + 5 行重复
    assert len(data["leases"]) == 140
    assert len(data["units"]) == 180
    assert len(data["activities"]) == 900
    assert len({a["session_id"] for a in data["activities"]}) == 60
    assert len(data["interactions"]) == 1500
