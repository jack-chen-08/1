"""数据范围与生命周期：跨 org 隔离、软删除、finance 阶段过滤、历史金额裁剪、合并语义。"""

from __future__ import annotations


def test_org_isolation_admin_b_sees_only_own_org(as_user, seed):
    body = as_user("admin_b").get("/api/crm/opportunities").json()
    assert body["summary"]["count"] == 1
    assert body["items"][0]["company_name"] == "壬文旅"


def test_cross_org_detail_is_404(as_user, seed):
    r = as_user("admin_a").get(f"/api/crm/opportunities/{seed['ids']['o_orgb_new']}")
    assert r.status_code == 404


def test_sales_cannot_read_others_opportunity(as_user, seed):
    """sales 读他人商机 404（不是 403 —— 不泄露存在性）。"""
    r = as_user("sales1").get(f"/api/crm/opportunities/{seed['ids']['o_s1_new2']}")
    assert r.status_code == 404


def test_site_scope_limits_second_site(as_user, seed):
    """sales1 只挂 S1，看不到 S2 的商机；org_admin 不受场地限制。

    注意：本用例对 sales 而言 owner 过滤也会挡住 S2 商机（o_s2_qual 属 sales2），
    因此它**不能**单独证明 site 闸门有效；真正的隔离用例见下面三条。
    """
    assert as_user("sales1").get(f"/api/crm/opportunities/{seed['ids']['o_s2_qual']}").status_code == 404
    assert as_user("admin_a").get(f"/api/crm/opportunities/{seed['ids']['o_s2_qual']}").status_code == 200


def test_site_scope_blocks_ops_manager_other_site(as_user, seed):
    """隔离 site 闸门：ops_manager 挂 S1、owner_scope=all、无 stage 过滤，
    唯一能挡住 S2 商机的就是 site 范围本身（去掉该过滤必然变红）。"""
    assert as_user("ops_a").get(f"/api/crm/opportunities/{seed['ids']['o_s2_qual']}").status_code == 404
    assert as_user("admin_a").get(f"/api/crm/opportunities/{seed['ids']['o_s2_qual']}").status_code == 200


def test_site_scope_excludes_other_site_from_list_and_summary(as_user, seed):
    """列表与汇总必须是同一套 site 口径：S2 商机不能进 items，也不能进 count。"""
    body = as_user("ops_a").get("/api/crm/opportunities").json()
    names = {item["company_name"] for item in body["items"]}
    assert "辛环保" not in names, "S2 商机不应出现在 S1 用户的列表里"
    assert body["summary"]["count"] == len(body["items"]), "汇总数量必须与可见条目一致"

    admin_view = as_user("admin_a").get("/api/crm/opportunities").json()
    assert "辛环保" in {item["company_name"] for item in admin_view["items"]}


def test_site_scope_still_blocks_finance_after_stage_filter(db, as_user, seed):
    """finance 叠加 stage=won 与 site 两道闸门：S2 上的 won 通过 stage 后仍须被 site 拦住。"""
    from crm.models import Opportunity

    other_site_won = Opportunity(
        org_id=seed["org_a"],
        site_id=seed["s2"],
        company_name="癸智算",
        stage="won",
        owner_id="lead_a",
        expected_first_year_amount_fen=1_234_000,
        weighted_amount_fen=1_234_000,
        created_by="lead_a",
    )
    db.add(other_site_won)
    db.commit()

    finance_body = as_user("fin_a").get("/api/crm/opportunities").json()
    assert finance_body["summary"]["count"] == 1
    assert {item["company_name"] for item in finance_body["items"]} == {"庚能源"}

    admin_names = {
        item["company_name"]
        for item in as_user("admin_a").get("/api/crm/opportunities").json()["items"]
    }
    assert "癸智算" in admin_names, "对照组：org_admin 应看到 S2 的 won"


def test_create_on_site_outside_scope_is_403(as_user, seed):
    """建档同样受 site 范围约束：不能把商机建到本人未挂的场地上。"""
    r = as_user("ops_a").post(
        "/api/crm/opportunities",
        json={"company_name": "越界公司", "site_id": str(seed["s2"]),
              "expected_first_year_amount_fen": 1_000},
    )
    assert r.status_code == 403


def test_finance_reads_only_won(as_user, seed):
    body = as_user("fin_a").get("/api/crm/opportunities").json()
    assert body["summary"]["stage_counts"] == {"won": 1}
    assert {item["stage"] for item in body["items"]} == {"won"}
    # 未成交商机的详情对 finance 不可见
    assert as_user("fin_a").get(f"/api/crm/opportunities/{seed['ids']['o_s1_new']}").status_code == 404


def test_finance_cannot_write(as_user, seed):
    r = as_user("fin_a").patch(
        f"/api/crm/opportunities/{seed['ids']['o_s1_won']}",
        json={"expected_first_year_amount_fen": 1},
    )
    assert r.status_code == 403


def test_soft_delete_hides_from_list_and_detail(as_user, seed):
    cli = as_user("lead_a")
    oid = seed["ids"]["o_s1_new"]
    before = cli.get("/api/crm/opportunities").json()["summary"]["count"]
    assert cli.delete(f"/api/crm/opportunities/{oid}").status_code == 200
    assert cli.get(f"/api/crm/opportunities/{oid}").status_code == 404
    assert cli.get("/api/crm/opportunities").json()["summary"]["count"] == before - 1


def test_viewer_history_masks_amount_fields(as_user, seed):
    """历史接口同样受金额可见性约束：viewer 看不到金额变更的具体数值。"""
    cli = as_user("lead_a")
    oid = seed["ids"]["o_s1_qual"]
    assert cli.patch(
        f"/api/crm/opportunities/{oid}", json={"expected_first_year_amount_fen": 250_000}
    ).status_code == 200

    viewer_rows = as_user("view_a").get(f"/api/crm/opportunities/{oid}/history").json()["items"]
    amount_rows = [r for r in viewer_rows if r["field"] == "expected_first_year_amount_fen"]
    assert amount_rows, "金额变更应留痕"
    assert all(r["old_value"] is None and r["new_value"] is None for r in amount_rows)
    assert amount_rows[0]["amount_hidden"] is True

    lead_rows = cli.get(f"/api/crm/opportunities/{oid}/history").json()["items"]
    lead_amount_rows = [r for r in lead_rows if r["field"] == "expected_first_year_amount_fen"]
    assert lead_amount_rows[0]["new_value"] == "250000"


def test_merge_sums_amounts_and_soft_deletes_source(as_user, seed):
    cli = as_user("lead_a")
    source = seed["ids"]["o_s1_new"]    # 100_000 / 30_000
    target = seed["ids"]["o_s1_prop"]   # 300_000 / 180_000

    body = cli.post(
        "/api/crm/opportunities/merge",
        json={"source_id": str(source), "target_id": str(target)},
    ).json()
    assert body["target"]["expected_first_year_amount_fen"] == 400_000
    assert body["target"]["weighted_amount_fen"] == 210_000
    assert cli.get(f"/api/crm/opportunities/{source}").status_code == 404


def test_create_rejects_duplicate_but_force_create_overrides(as_user, seed):
    cli = as_user("sales1")
    payload = {"company_name": "甲科技", "site_id": str(seed["s1"]),
               "expected_first_year_amount_fen": 50_000}
    conflict = cli.post("/api/crm/opportunities", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "duplicate_conflict"

    forced = as_user("lead_a").post("/api/crm/opportunities/force-create", json=payload)
    assert forced.status_code == 201
    assert forced.json()["duplicate_conflicts_overridden"] >= 1


def test_sales_create_forces_self_as_owner(as_user, seed):
    r = as_user("sales1").post(
        "/api/crm/opportunities",
        json={"company_name": "新建公司X", "site_id": str(seed["s1"]),
              "owner_id": "sales2", "expected_first_year_amount_fen": 10_000},
    )
    assert r.status_code == 201
    assert r.json()["owner_id"] == "sales1"


def test_patch_owner_id_cannot_escape_scope(as_user, seed):
    """编辑时改负责人：sales 一律落回本人（不能把商机转出去），
    其他角色只可指派同 org 用户，指派不存在的人返回 422。"""
    oid = seed["ids"]["o_s1_new"]

    escaped = as_user("sales1").patch(
        f"/api/crm/opportunities/{oid}", json={"owner_id": "sales2"}
    )
    assert escaped.status_code == 200
    assert escaped.json()["owner_id"] == "sales1", "sales 不能把商机转给他人"

    bad = as_user("lead_a").patch(
        f"/api/crm/opportunities/{oid}", json={"owner_id": "no_such_user"}
    )
    assert bad.status_code == 422

    moved = as_user("lead_a").patch(
        f"/api/crm/opportunities/{oid}", json={"owner_id": "sales2"}
    )
    assert moved.status_code == 200
    assert moved.json()["owner_id"] == "sales2"
