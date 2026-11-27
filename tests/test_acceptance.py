"""四条验收条款逐条对应的断言（条款编号见 README §验收对照）。

AC1 由 test_matrix_spec.py + test_matrix_combinations.py 覆盖（矩阵每个组合都有用例且全绿）；
本文件覆盖 AC2、AC3、AC4。
"""

from __future__ import annotations

import uuid

from crm.models import AppUser, Opportunity

AMOUNT_KEYS = {
    "expected_first_year_amount_fen",
    "weighted_amount_fen",
    "amount_total_fen",
    "weighted_total_fen",
}


def _walk_amount_keys(node, path=""):
    """递归找出所有金额键的取值。"""
    hits = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in AMOUNT_KEYS:
                hits.append((f"{path}/{key}", value))
            hits.extend(_walk_amount_keys(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            hits.extend(_walk_amount_keys(value, f"{path}[{idx}]"))
    return hits


# --------------------------------------------------------------------------- #
# AC2：两名 sales 各有 3 条商机时，每人 summary.amount_total_fen 只等于自己 3 条之和
# --------------------------------------------------------------------------- #
def test_ac2_sales_summary_counts_only_own_three(db, as_user):
    org = uuid.uuid4()
    site = uuid.uuid4()
    db.add_all(
        [
            AppUser(id="ac2_s1", org_id=org, role="sales", site_ids=[str(site)], display_name="甲"),
            AppUser(id="ac2_s2", org_id=org, role="sales", site_ids=[str(site)], display_name="乙"),
        ]
    )

    amounts_1 = [111_100, 222_200, 333_300]
    amounts_2 = [900_000, 800_000, 700_000]
    for owner, amounts in (("ac2_s1", amounts_1), ("ac2_s2", amounts_2)):
        for idx, amount in enumerate(amounts):
            db.add(
                Opportunity(
                    org_id=org,
                    site_id=site,
                    company_name=f"{owner}-公司{idx}",
                    stage="qualified",
                    owner_id=owner,
                    expected_first_year_amount_fen=amount,
                    weighted_amount_fen=amount // 3,
                    created_by=owner,
                )
            )
    db.commit()

    for user_id, amounts in (("ac2_s1", amounts_1), ("ac2_s2", amounts_2)):
        body = as_user(user_id).get("/api/crm/opportunities").json()
        assert len(body["items"]) == 3, body
        assert {item["owner_id"] for item in body["items"]} == {user_id}
        assert body["summary"]["count"] == 3
        assert body["summary"]["amount_total_fen"] == sum(amounts)
        assert body["summary"]["weighted_total_fen"] == sum(a // 3 for a in amounts)

    # 两人互不污染：600+ 与 900+ 两套和值不相同，若越权统计必然对不上
    assert sum(amounts_1) != sum(amounts_2)


# --------------------------------------------------------------------------- #
# AC3：viewer 的详情、列表与 summary 中都不出现金额数值
# --------------------------------------------------------------------------- #
def test_ac3_viewer_sees_no_amount_values(as_user, seed):
    cli = as_user("view_a")
    detail = cli.get(f"/api/crm/opportunities/{seed['ids']['o_s1_qual']}")
    listing = cli.get("/api/crm/opportunities")

    assert detail.status_code == 200 and listing.status_code == 200

    for payload in (detail.json(), listing.json()):
        for path, value in _walk_amount_keys(payload):
            assert value is None, f"viewer 不应看到金额数值：{path}={value}"

    # 金额字段存在但为 null，且带 amount_hidden 标记
    assert detail.json()["expected_first_year_amount_fen"] is None
    assert detail.json()["weighted_amount_fen"] is None
    assert detail.json()["amount_hidden"] is True
    assert all(item["amount_hidden"] is True for item in listing.json()["items"])

    # summary 干脆不下发金额键
    summary = listing.json()["summary"]
    assert "amount_total_fen" not in summary
    assert "weighted_total_fen" not in summary
    assert summary["count"] >= 1

    # 对照组：同一批数据，sales 与 lead 能看到金额数值
    for user_id in ("sales1", "lead_a"):
        body = as_user(user_id).get("/api/crm/opportunities").json()
        values = [v for _, v in _walk_amount_keys(body)]
        assert any(isinstance(v, int) and v > 0 for v in values), user_id


# --------------------------------------------------------------------------- #
# AC4：撞单检查返回给 sales 的数据不含金额字段
# --------------------------------------------------------------------------- #
def test_ac4_duplicate_check_hides_amounts_for_sales(db, as_user, seed):
    site = seed["s1"]
    org = seed["org_a"]
    for idx in range(2):
        db.add(
            Opportunity(
                org_id=org,
                site_id=site,
                company_name="重复空间公司",
                stage="qualified",
                owner_id="sales2",
                expected_first_year_amount_fen=500_000 + idx,
                weighted_amount_fen=200_000 + idx,
                space_requirement="1200㎡厂房",
                created_by="sales2",
            )
        )
    db.commit()

    body = as_user("sales1").post(
        "/api/crm/opportunities/duplicate-check",
        json={"company_name": "重复空间公司 ", "site_id": str(site),
              "space_requirement": "1200㎡厂房"},
    ).json()

    assert body["count"] >= 2
    for item in body["matches"]:
        assert set(item) == {"id", "stage", "owner_id", "owner_name"}, item
        assert "expected_first_year_amount_fen" not in item
        assert "weighted_amount_fen" not in item
        assert "space_requirement" not in item
        assert item["owner_id"] == "sales2"
        assert item["owner_name"] == "业务员二"

    # 对照组：sales_lead 走完整投影
    lead_body = as_user("lead_a").post(
        "/api/crm/opportunities/duplicate-check",
        json={"company_name": "重复空间公司", "site_id": str(site)},
    ).json()
    lead_item = lead_body["matches"][0]
    assert lead_item["expected_first_year_amount_fen"] > 0
    assert lead_item["space_requirement"] == "1200㎡厂房"
