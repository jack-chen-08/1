"""权限矩阵装载与判定。

矩阵文件：crm/permissions/matrix/opportunity.yaml（唯一真源）。
代码不复制矩阵内容 —— 判定一律从文件读，改矩阵即改行为，
参数化测试直接遍历矩阵里的角色与动作。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from crm.config import DEFAULT_MATRIX

# 矩阵里 actions 下可出现的动作名（与接口一一对应）
ACTIONS = (
    "read",
    "write",
    "duplicate_check",
    "force_create",
    "delete",
    "merge",
)


class MatrixError(ValueError):
    """矩阵文件不合规。"""


@dataclass(frozen=True)
class RolePolicy:
    key: str
    label: str
    site_scope: str
    owner_scope: str
    stage_in: tuple[str, ...] | None
    read: bool
    write: bool
    duplicate_check: bool
    advance_as_owner: bool
    advance_by_role: bool
    force_create: bool
    delete: bool
    merge: bool
    amounts_visible: bool
    amount_null_fields: tuple[str, ...]
    amount_hidden_flag: bool

    def action_allowed(self, action: str) -> bool:
        if action not in ACTIONS:
            raise MatrixError(f"unknown action: {action}")
        return bool(getattr(self, action))


@dataclass(frozen=True)
class Matrix:
    path: Path
    policy_version: str
    roles: dict[str, RolePolicy]
    stage_graph: dict[str, list[str]]
    duplicate_minimal_roles: tuple[str, ...]
    duplicate_minimal_fields: tuple[str, ...]
    duplicate_full_fields: tuple[str, ...]

    # ---------- 判定 ----------

    def policy(self, role: str) -> RolePolicy:
        try:
            return self.roles[role]
        except KeyError as exc:
            raise MatrixError(f"role not in matrix: {role}") from exc

    def can(self, role: str, action: str) -> bool:
        return self.policy(role).action_allowed(action)

    def can_advance_stage(self, role: str, is_owner: bool) -> bool:
        """阶段推进：负责人本人，或矩阵里 by_role=true 的角色（sales_lead）。"""
        pol = self.policy(role)
        return (pol.advance_as_owner and is_owner) or pol.advance_by_role

    def can_change_to(self, from_stage: str, to_stage: str) -> bool:
        return to_stage in self.stage_graph.get(from_stage, [])

    def duplicate_projection(self, role: str) -> tuple[str, ...]:
        """撞单检查的字段投影：sales 走最小投影。"""
        if role in self.duplicate_minimal_roles:
            return self.duplicate_minimal_fields
        return self.duplicate_full_fields


def _need(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise MatrixError(f"missing key '{key}' in {where}")
    return mapping[key]


def load_matrix(path: str | Path | None = None) -> Matrix:
    """读并校验矩阵文件。"""
    p = Path(path or DEFAULT_MATRIX)
    with p.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    roles: dict[str, RolePolicy] = {}
    for key, body in _need(raw, "roles", str(p)).items():
        actions = _need(body, "actions", f"roles.{key}")
        advance = _need(actions, "advance_stage", f"roles.{key}.actions")
        amounts = _need(body, "amounts", f"roles.{key}")
        site_scope = _need(body, "site_scope", f"roles.{key}")
        owner_scope = _need(body, "owner_scope", f"roles.{key}")
        if site_scope not in {"all_in_org", "own_sites"}:
            raise MatrixError(f"roles.{key}.site_scope 非法: {site_scope}")
        if owner_scope not in {"all", "own"}:
            raise MatrixError(f"roles.{key}.owner_scope 非法: {owner_scope}")
        stage_in = body.get("stage_in")
        roles[key] = RolePolicy(
            key=key,
            label=str(body.get("label", key)),
            site_scope=site_scope,
            owner_scope=owner_scope,
            stage_in=tuple(stage_in) if stage_in else None,
            read=bool(actions["read"]),
            write=bool(actions["write"]),
            duplicate_check=bool(actions["duplicate_check"]),
            advance_as_owner=bool(advance["as_owner"]),
            advance_by_role=bool(advance["by_role"]),
            force_create=bool(actions["force_create"]),
            delete=bool(actions["delete"]),
            merge=bool(actions["merge"]),
            amounts_visible=bool(amounts["visible"]),
            amount_null_fields=tuple(amounts.get("null_fields") or ()),
            amount_hidden_flag=bool(amounts.get("amount_hidden_flag", False)),
        )

    proj = _need(raw, "duplicate_check_projection", str(p))
    return Matrix(
        path=p,
        policy_version=str(raw.get("policy_version", "unversioned")),
        roles=roles,
        stage_graph={k: list(v or []) for k, v in _need(raw, "stage_graph", str(p)).items()},
        duplicate_minimal_roles=tuple(proj["minimal_roles"]),
        duplicate_minimal_fields=tuple(proj["minimal_fields"]),
        duplicate_full_fields=tuple(proj["full_fields"]),
    )


_CACHE: dict[tuple[str, float], Matrix] = {}


def get_matrix(path: str | Path | None = None) -> Matrix:
    """带缓存装载（按路径 + mtime 失效，改矩阵即时生效）。"""
    p = Path(path or DEFAULT_MATRIX).resolve()
    key = (str(p), p.stat().st_mtime)
    if key not in _CACHE:
        _CACHE[key] = load_matrix(p)
    return _CACHE[key]
