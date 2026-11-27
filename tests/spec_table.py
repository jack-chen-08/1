"""需求原文 → 权限规则表（人工逐条转写，独立于 opportunity.yaml）。

放在单独模块，供
    test_matrix_spec.py          —— 校验 YAML 与转写表一致
    test_matrix_combinations.py  —— 以转写表为预期，逐个组合打真接口
共同引用，避免「实现自己证明自己」。
"""

from __future__ import annotations

T, F = True, False

#   规则原文摘录：
#     · 只看本 org、本人 site_ids 内的商机（org_admin 不受场地限制）
#     · sales 只能读写自己负责的商机，他人商机返回 404
#     · sales_lead 与 ops_manager 可读写本场地全部商机
#     · finance 只读本场地 stage=won 的商机
#     · viewer 只读本场地全部商机，金额字段 null + amount_hidden=true
#     · 阶段推进允许负责人与 sales_lead
#     · force_create 只授予 sales_lead 与 org_admin
#     · 删除与合并只允许 sales_lead 与 org_admin
SPEC = {
    "org_admin": dict(
        site_scope="all_in_org", owner_scope="all", stage_in=None,
        read=T, write=T, duplicate_check=T, force_create=T, delete=T, merge=T,
        advance_as_owner=T, advance_by_role=F, amounts_visible=T,
    ),
    "ops_manager": dict(
        site_scope="own_sites", owner_scope="all", stage_in=None,
        read=T, write=T, duplicate_check=T, force_create=F, delete=F, merge=F,
        advance_as_owner=T, advance_by_role=F, amounts_visible=T,
    ),
    "sales_lead": dict(
        site_scope="own_sites", owner_scope="all", stage_in=None,
        read=T, write=T, duplicate_check=T, force_create=T, delete=T, merge=T,
        advance_as_owner=T, advance_by_role=T, amounts_visible=T,
    ),
    "sales": dict(
        site_scope="own_sites", owner_scope="own", stage_in=None,
        read=T, write=T, duplicate_check=T, force_create=F, delete=F, merge=F,
        advance_as_owner=T, advance_by_role=F, amounts_visible=T,
    ),
    "finance": dict(
        site_scope="own_sites", owner_scope="all", stage_in=("won",),
        read=T, write=F, duplicate_check=T, force_create=F, delete=F, merge=F,
        advance_as_owner=F, advance_by_role=F, amounts_visible=T,
    ),
    "viewer": dict(
        site_scope="own_sites", owner_scope="all", stage_in=None,
        read=T, write=F, duplicate_check=T, force_create=F, delete=F, merge=F,
        advance_as_owner=F, advance_by_role=F, amounts_visible=F,
    ),
}

ROLE_KEYS = sorted(SPEC)

# 每个角色在基线数据里的登录 id
ROLE_USER = {
    "org_admin": "admin_a",
    "ops_manager": "ops_a",
    "sales_lead": "lead_a",
    "sales": "sales1",
    "finance": "fin_a",
    "viewer": "view_a",
}
