"""可见范围矩阵装载与校验。

矩阵文件是唯一真源；本模块只负责「读 + 校验 + 缓存 + 换算」，
不承担任何权限判断（判断在 visibility.py，且只依赖本模块换算出的白名单）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


class MatrixError(ValueError):
    """矩阵配置非法。"""


@dataclass(frozen=True)
class RoleSpec:
    key: str
    rank: int
    label: str


@dataclass(frozen=True)
class CategorySpec:
    key: str
    min_rank: int
    label: str
    restricted: bool = False


@dataclass(frozen=True)
class VisibilityMatrix:
    version: str
    roles: Mapping[str, RoleSpec]
    categories: Mapping[str, CategorySpec]
    staff_audiences: tuple[str, ...]
    member_audiences: tuple[str, ...]
    member_categories: tuple[str, ...]

    # —— 换算：矩阵 → 过滤条件用的白名单 ——

    def rank_of(self, role: str) -> int:
        spec = self.roles.get(role)
        if spec is None:
            raise MatrixError(f"未知岗位：{role}")
        return spec.rank

    def categories_for_rank(self, rank: int) -> tuple[str, ...]:
        """该岗位层级可访问的类别白名单（按 min_rank 换算）。"""
        return tuple(
            name for name, spec in self.categories.items() if rank >= spec.min_rank
        )

    def restricted_categories(self) -> tuple[str, ...]:
        return tuple(n for n, s in self.categories.items() if s.restricted)


_CACHE: dict[tuple[str, float], VisibilityMatrix] = {}


def parse_matrix(raw: dict) -> VisibilityMatrix:
    if not isinstance(raw, dict):
        raise MatrixError("矩阵根节点必须是映射")

    roles_raw = raw.get("staff_roles") or {}
    if not isinstance(roles_raw, dict) or not roles_raw:
        raise MatrixError("staff_roles 缺失或为空")
    roles: dict[str, RoleSpec] = {}
    seen_ranks: dict[int, str] = {}
    for key, body in roles_raw.items():
        rank = (body or {}).get("rank")
        if not isinstance(rank, int) or rank < 1:
            raise MatrixError(f"{key}.rank 必须是 ≥1 的整数")
        if rank in seen_ranks:
            raise MatrixError(f"rank 重复：{key} 与 {seen_ranks[rank]} 同为 {rank}")
        seen_ranks[rank] = key
        roles[key] = RoleSpec(key=key, rank=rank, label=str((body or {}).get("label", key)))

    cats_raw = raw.get("categories") or {}
    if not isinstance(cats_raw, dict) or not cats_raw:
        raise MatrixError("categories 缺失或为空")
    categories: dict[str, CategorySpec] = {}
    for key, body in cats_raw.items():
        body = body or {}
        min_rank = body.get("min_rank")
        if not isinstance(min_rank, int) or min_rank < 1:
            raise MatrixError(f"{key}.min_rank 必须是 ≥1 的整数")
        if min_rank not in seen_ranks:
            raise MatrixError(f"{key}.min_rank={min_rank} 未命中任何岗位 rank")
        categories[key] = CategorySpec(
            key=key,
            min_rank=min_rank,
            label=str(body.get("label", key)),
            restricted=bool(body.get("restricted", False)),
        )

    staff_audiences = tuple(raw.get("staff_audiences") or ())
    if not staff_audiences:
        raise MatrixError("staff_audiences 缺失或为空")
    member_ctx = raw.get("member_context") or {}
    member_audiences = tuple(member_ctx.get("audiences") or ())
    if not member_audiences:
        raise MatrixError("member_context.audiences 缺失或为空")
    member_categories = tuple(member_ctx.get("categories") or ())
    if not member_categories:
        raise MatrixError("member_context.categories 缺失或为空")
    unknown = set(member_categories) - set(categories)
    if unknown:
        raise MatrixError(f"member_context.categories 含未知类别：{sorted(unknown)}")

    return VisibilityMatrix(
        version=str(raw.get("version", "unversioned")),
        roles=roles,
        categories=categories,
        staff_audiences=staff_audiences,
        member_audiences=member_audiences,
        member_categories=member_categories,
    )


def load_matrix(path: str | Path | None = None) -> VisibilityMatrix:
    """按 mtime 缓存，改文件即生效，无需重启进程。"""
    if path is None:
        path = Path(__file__).parent / "visibility_matrix.yaml"
    p = Path(path)
    if not p.exists():
        raise MatrixError(f"矩阵文件不存在：{p}")
    key = (str(p.resolve()), p.stat().st_mtime)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    matrix = parse_matrix(raw)
    _CACHE.clear()
    _CACHE[key] = matrix
    return matrix
