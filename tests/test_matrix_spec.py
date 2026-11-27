"""矩阵 vs 需求原文：把工单规则表独立抄在 tests/spec_table.py，与 opportunity.yaml 对比。

矩阵文件不是「自己证明自己」：
    需求原文 → (人工逐条转写) → SPEC  ←对比→  opportunity.yaml
行为侧由 test_matrix_combinations.py 拿 SPEC 当预期去打真接口。
"""

from __future__ import annotations

import pytest

from crm.permissions.matrix_loader import get_matrix
from spec_table import ROLE_KEYS, SPEC


def test_matrix_covers_exactly_the_six_roles() -> None:
    assert sorted(get_matrix().roles) == ROLE_KEYS


@pytest.mark.parametrize("role", ROLE_KEYS)
@pytest.mark.parametrize("field", ["site_scope", "owner_scope", "stage_in"])
def test_matrix_scope_matches_spec(role: str, field: str) -> None:
    actual = getattr(get_matrix().policy(role), field)
    assert actual == SPEC[role][field], f"{role}.{field}: {actual} != {SPEC[role][field]}"


@pytest.mark.parametrize("role", ROLE_KEYS)
@pytest.mark.parametrize(
    "field",
    [
        "read", "write", "duplicate_check", "force_create", "delete", "merge",
        "advance_as_owner", "advance_by_role", "amounts_visible",
    ],
)
def test_matrix_actions_match_spec(role: str, field: str) -> None:
    assert getattr(get_matrix().policy(role), field) is SPEC[role][field], f"{role}.{field}"


def test_viewer_amount_rules_match_spec() -> None:
    pol = get_matrix().policy("viewer")
    assert pol.amounts_visible is False
    assert set(pol.amount_null_fields) == {"expected_first_year_amount_fen", "weighted_amount_fen"}
    assert pol.amount_hidden_flag is True


def test_duplicate_projection_matches_spec() -> None:
    matrix = get_matrix()
    assert matrix.duplicate_minimal_roles == ("sales",)
    assert set(matrix.duplicate_minimal_fields) == {"id", "stage", "owner_id", "owner_name"}
    assert not ({"expected_first_year_amount_fen", "space_requirement"} &
                set(matrix.duplicate_minimal_fields))


def test_stage_graph_is_forward_only() -> None:
    graph = get_matrix().stage_graph
    assert graph["proposal"] == ["won", "lost"]
    assert graph["won"] == []
    for stage, nxt in graph.items():
        assert stage not in nxt
