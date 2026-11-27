"""矩阵全组合行为测试：角色 × 动作，逐个打真接口。

预期来自 tests/spec_table.py（需求原文转写），不是权限矩阵文件本身，
因此这组用例证明的是「实现符合需求」，而不是「实现等于自己」。
"""

from __future__ import annotations

import uuid

import pytest

from spec_table import ROLE_KEYS, ROLE_USER, SPEC

ACTIONS = ["read", "write", "duplicate_check", "force_create", "delete", "merge"]


def _new_company() -> str:
    return f"评审公司{uuid.uuid4().hex[:8]}"


@pytest.mark.parametrize("role", ROLE_KEYS)
@pytest.mark.parametrize("action", ACTIONS)
def test_action_matrix(role, action, as_user, seed):
    cli = as_user(ROLE_USER[role])
    site = str(seed["s1"])
    allowed = SPEC[role][action]

    if action == "read":
        r = cli.get("/api/crm/opportunities")
    elif action == "write":
        r = cli.post(
            "/api/crm/opportunities",
            json={"company_name": _new_company(), "site_id": site,
                  "expected_first_year_amount_fen": 1000},
        )
    elif action == "duplicate_check":
        r = cli.post(
            "/api/crm/opportunities/duplicate-check",
            json={"company_name": _new_company(), "site_id": site},
        )
    elif action == "force_create":
        r = cli.post(
            "/api/crm/opportunities/force-create",
            json={"company_name": _new_company(), "site_id": site},
        )
    elif action == "delete":
        r = cli.delete(f"/api/crm/opportunities/{seed['ids']['o_s1_new']}")
    elif action == "merge":
        r = cli.post(
            "/api/crm/opportunities/merge",
            json={"source_id": str(seed["ids"]["o_s1_new"]),
                  "target_id": str(seed["ids"]["o_s1_prop"])},
        )
    else:  # pragma: no cover
        raise AssertionError(action)

    if allowed:
        assert r.status_code in (200, 201), f"{role}/{action} 应放行，实际 {r.status_code}: {r.text}"
    else:
        assert r.status_code == 403, f"{role}/{action} 应 403，实际 {r.status_code}: {r.text}"


# --------------------------------------------------------------------------- #
# 阶段推进：负责人维度 × 角色维度（规则：负责人与 sales_lead）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", ROLE_KEYS)
def test_advance_other_users_opportunity(role, as_user, seed):
    """推进「他人名下」商机：owner_scope=own 的角色看不到（404），
    stage_in 过滤掉的看不到（404），其余按 advance_by_role 判 200/403。"""
    cli = as_user(ROLE_USER[role])
    target = seed["ids"]["o_s1_new2"]  # sales2 名下、stage=new
    r = cli.post(f"/api/crm/opportunities/{target}/advance", json={"to_stage": "qualified"})

    spec = SPEC[role]
    if spec["owner_scope"] == "own" or spec["stage_in"]:
        expected = 404
    else:
        expected = 200 if spec["advance_by_role"] else 403
    assert r.status_code == expected, f"{role}: {r.status_code} != {expected} / {r.text}"


def test_owner_may_advance_own_opportunity(as_user, seed):
    """负责人本人可推进自己的商机（sales 也能）。"""
    cli = as_user("sales1")
    r = cli.post(
        f"/api/crm/opportunities/{seed['ids']['o_s1_new']}/advance",
        json={"to_stage": "qualified", "note": "客户确认预算"},
    )
    assert r.status_code == 200
    assert r.json()["stage"] == "qualified"

    timeline = cli.get(f"/api/crm/opportunities/{seed['ids']['o_s1_new']}/stage-timeline").json()
    assert [row["to_stage"] for row in timeline["items"]] == ["new", "qualified"]

    history = cli.get(f"/api/crm/opportunities/{seed['ids']['o_s1_new']}/history").json()
    assert any(row["field"] == "stage" and row["new_value"] == "qualified"
               for row in history["items"])


def test_illegal_stage_transition_rejected(as_user, seed):
    cli = as_user("lead_a")
    r = cli.post(
        f"/api/crm/opportunities/{seed['ids']['o_s1_new']}/advance",
        json={"to_stage": "won"},
    )
    assert r.status_code == 409
